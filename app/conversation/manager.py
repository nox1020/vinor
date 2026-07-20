from __future__ import annotations

import re
import time

from app.conversation.config import conversation_early_return
from app.conversation.interfaces import (
    INTENT_CONTRACT,
    INTENT_DEAL,
    INTENT_OFFER,
    INTENT_VISIT,
    INTENT_VISIT_RESULT,
    STATE_CANCELLED,
    STATE_COLLECTING,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INIT,
    STATE_READY,
    STATE_START,
    STATE_VALIDATING,
    STATE_WAITING,
    STATE_WAITING_USER,
    WF_NONE,
    ConversationManager,
    ConversationOutcome,
    ConversationSession,
    IdentityResolver,
    IntentResolver,
    RoleResolver,
    SessionStore,
    WorkflowResolver,
)
from app.conversation.session import new_session
from app.workflow.config import workflow_engine_enabled
from app.workflow.di import make_workflow_engine
from app.workflow.interfaces import (
    ACTIVE_STATES,
    WorkflowContext,
    WorkflowEngine,
    WorkflowEngineResult,
)

_CANCEL_RE = re.compile(r"(لغو|انصراف|بی‌خیال|cancel)", re.I)


def _session_to_ctx(session: ConversationSession) -> WorkflowContext:
    return WorkflowContext(
        workflow_id=session.workflow_id,
        workflow_name=session.workflow_name or "",
        state=session.state,
        current_step=session.current_step,
        collected=dict(session.collected or {}),
        missing=list(session.missing or []),
        completed_steps=list(session.completed_steps or []),
        validation_errors=list(session.validation_errors or []),
        role=session.role,
        intent=session.intent,
        object_type=session.object_type,
        user_key=session.user_key,
        started_at=session.started_at,
        updated_at=session.updated_at,
        metadata=dict(session.metadata or {}),
    )


def _apply_ctx(session: ConversationSession, ctx: WorkflowContext) -> ConversationSession:
    session.workflow_id = ctx.workflow_id
    session.workflow_name = ctx.workflow_name
    session.state = ctx.state
    session.current_step = ctx.current_step
    session.collected = dict(ctx.collected or {})
    session.missing = list(ctx.missing or [])
    session.completed_steps = list(ctx.completed_steps or [])
    session.validation_errors = list(ctx.validation_errors or [])
    session.object_type = ctx.object_type
    session.intent = ctx.intent or session.intent
    session.role = ctx.role or session.role
    session.started_at = ctx.started_at or session.started_at
    session.updated_at = ctx.updated_at
    session.metadata = dict(ctx.metadata or {})
    return session


def _legacy_active(state: str) -> bool:
    return state in (
        STATE_COLLECTING,
        STATE_START,
        STATE_WAITING,
        STATE_INIT,
        STATE_VALIDATING,
        STATE_WAITING_USER,
        STATE_READY,
    ) or state in ACTIVE_STATES


class DefaultConversationManager(ConversationManager):
    def __init__(
        self,
        *,
        identity: IdentityResolver,
        roles: RoleResolver,
        intents: IntentResolver,
        workflows: WorkflowResolver,
        sessions: SessionStore,
        engine: WorkflowEngine | None = None,
    ):
        self._identity = identity
        self._roles = roles
        self._intents = intents
        self._workflows = workflows
        self._sessions = sessions
        self._engine = engine
        if self._engine is None and workflow_engine_enabled():
            self._engine = make_workflow_engine()

    def handle(
        self,
        *,
        message: str,
        user_key: str,
        audience: str,
        voice: str = "",
        chip_intent: str = "",
        thread_id: str | None = None,
    ) -> ConversationOutcome:
        t0 = time.time()
        msg = (message or "").strip()
        tid = (thread_id or "").strip() or None
        identity = self._identity.resolve(user_key=user_key, audience=audience)
        role = self._roles.resolve(identity)
        intent_info = self._intents.resolve(message=msg, chip_intent=chip_intent)
        workflow_id = self._workflows.resolve(intent_info.intent)

        session = self._sessions.load(user_key, thread_id=tid) or new_session(
            user_key=user_key, role=role, thread_id=tid
        )
        session.role = role
        if tid:
            meta = dict(session.metadata or {})
            meta["thread_id"] = tid
            session.metadata = meta

        # Cancel active workflow
        if session.workflow_id and session.workflow_id != WF_NONE and _CANCEL_RE.search(msg):
            if self._engine is not None:
                result = self._engine.cancel(ctx=_session_to_ctx(session))
                self._sessions.clear(user_key, thread_id=tid)
                return self._from_engine(result, identity, intent_info.intent, t0, clear=True)
            session.state = STATE_CANCELLED
            self._sessions.clear(user_key, thread_id=tid)
            obs = self._obs(session, identity, intent_info.intent, t0)
            return ConversationOutcome(
                handled=True,
                ok=True,
                reply="فرآیند لغو شد. هر وقت آماده بودید از نو شروع کنید.",
                session=None,
                pass_to_supervisor=False,
                extra_tokens=0,
                observability=obs,
            )

        # Continue active workflow via Engine
        active = (
            session.workflow_id
            and session.workflow_id != WF_NONE
            and _legacy_active(session.state)
        )
        # جلسهٔ گیرکرده روی «کد فایل» برای همکار با فایل معلوم → رها کن به ابزار AI
        if (
            active
            and str(session.current_step or "") == "land_code"
            and getattr(identity, "is_partner", False)
        ):
            try:
                from app.workflow.engine import _resolve_focus_land_code

                if _resolve_focus_land_code(user_key):
                    self._sessions.clear(user_key, thread_id=tid)
                    return ConversationOutcome(
                        handled=False,
                        ok=True,
                        pass_to_supervisor=True,
                        extra_tokens=0,
                        observability={
                            "detected_role": role,
                            "detected_intent": intent_info.intent or session.intent,
                            "workflow": WF_NONE,
                            "skip_reason": "unstick_land_code_step",
                            "conversation_extra_tokens": 0,
                            "workflow_extra_tokens": 0,
                        },
                    )
            except Exception:
                pass
        if active and self._engine is not None:
            result = self._engine.continue_(ctx=_session_to_ctx(session), message=msg)
            return self._persist_engine(session, result, identity, intent_info.intent, t0)

        if active and self._engine is None:
            # Should not happen when engine enabled; fail-open to supervisor
            self._sessions.clear(user_key, thread_id=tid)
            return ConversationOutcome(handled=False, pass_to_supervisor=True, extra_tokens=0)

        # Pass-through / general → Supervisor
        if workflow_id == WF_NONE or workflow_id == "general_conversation":
            # general_conversation is pass-through by design
            if self._engine is not None and workflow_id == "general_conversation":
                result = self._engine.start(
                    workflow_id=workflow_id,
                    user_key=user_key,
                    role=role,
                    intent=intent_info.intent,
                    message=msg,
                )
                return self._from_engine(result, identity, intent_info.intent, t0)

            obs = {
                "detected_role": role,
                "detected_intent": intent_info.intent,
                "workflow": WF_NONE,
                "workflow_name": "",
                "workflow_state": "",
                "conversation_state": "",
                "current_step": "",
                "completed_fields": [],
                "completed_steps": [],
                "missing_fields": [],
                "missing_steps": [],
                "validation_errors": [],
                "session_duration_ms": int((time.time() - t0) * 1000),
                "conversation_extra_tokens": 0,
                "workflow_extra_tokens": 0,
            }
            return ConversationOutcome(
                handled=False,
                ok=True,
                pass_to_supervisor=True,
                extra_tokens=0,
                observability=obs,
            )

        # Partner chat = مسیر زنده واحد (tools/cards). Workflow فرم فقط برای غیرهمکار.
        _partner_surface = bool(getattr(identity, "is_partner", False)) or (
            (audience or "").strip().lower() == "partner"
        )
        if _partner_surface:
            self._sessions.clear(user_key, thread_id=tid)
            return ConversationOutcome(
                handled=False,
                ok=True,
                pass_to_supervisor=True,
                extra_tokens=0,
                observability={
                    "detected_role": role,
                    "detected_intent": intent_info.intent,
                    "workflow": WF_NONE,
                    "workflow_name": "",
                    "workflow_state": "",
                    "skip_reason": "partner_chat_tools_only",
                    "persists_business": False,
                    "conversation_extra_tokens": 0,
                    "workflow_extra_tokens": 0,
                },
            )

        # Start new workflow via Engine
        if self._engine is not None:
            result = self._engine.start(
                workflow_id=workflow_id,
                user_key=user_key,
                role=role,
                intent=intent_info.intent,
                message=msg,
            )
            if not result.handled:
                return self._from_engine(result, identity, intent_info.intent, t0)
            session = new_session(user_key=user_key, role=role, thread_id=tid)
            return self._persist_engine(session, result, identity, intent_info.intent, t0)

        return ConversationOutcome(handled=False, pass_to_supervisor=True, extra_tokens=0)

    def _persist_engine(
        self,
        session: ConversationSession,
        result: WorkflowEngineResult,
        identity,
        intent: str,
        t0: float,
    ) -> ConversationOutcome:
        tid = None
        if isinstance(session.metadata, dict):
            tid = str(session.metadata.get("thread_id") or "").strip() or None
        if result.context is not None:
            # Preserve thread scope across engine context apply.
            prev_tid = tid
            _apply_ctx(session, result.context)
            if prev_tid:
                meta = dict(session.metadata or {})
                meta["thread_id"] = prev_tid
                session.metadata = meta
            terminal = result.context.state in (
                STATE_COMPLETED,
                STATE_FAILED,
                STATE_CANCELLED,
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            )
            if terminal:
                self._sessions.clear(session.user_key, thread_id=prev_tid)
            else:
                self._sessions.save(session)
        # Phase 0 Foundation: optional Activity/Timeline record (flags default ON).
        # Fail-open — never alters reply, session, or Supervisor handoff.
        try:
            from app.foundation.service import maybe_record_workflow_commit

            maybe_record_workflow_commit(result)
        except Exception:
            pass
        return self._from_engine(result, identity, intent, t0)

    def _from_engine(
        self,
        result: WorkflowEngineResult,
        identity,
        intent: str,
        t0: float,
        clear: bool = False,
    ) -> ConversationOutcome:
        obs = dict(result.observability or {})
        if identity is not None and hasattr(identity, "role"):
            obs.setdefault("detected_role", identity.role)
        obs.setdefault("detected_intent", intent)
        obs.setdefault("conversation_extra_tokens", 0)
        obs.setdefault("workflow_extra_tokens", result.extra_tokens)
        session = None
        if result.context is not None and not clear:
            session = new_session(user_key=result.context.user_key, role=result.context.role)
            _apply_ctx(session, result.context)
        return ConversationOutcome(
            handled=result.handled,
            ok=result.ok,
            reply=result.reply,
            session=session,
            structured_object=result.structured_object,
            pass_to_supervisor=result.pass_to_supervisor,
            extra_tokens=result.extra_tokens,
            observability=obs,
        )

    def _obs(self, session: ConversationSession, identity, intent: str, t0: float) -> dict:
        started = float(session.started_at or t0)
        return {
            "detected_role": identity.role if hasattr(identity, "role") else session.role,
            "detected_intent": intent or session.intent,
            "workflow": session.workflow_id,
            "workflow_name": session.workflow_name,
            "workflow_state": session.state,
            "conversation_state": session.state,
            "current_step": session.current_step,
            "completed_fields": list(session.collected.keys()),
            "completed_steps": list(session.completed_steps or []),
            "missing_fields": list(session.missing),
            "missing_steps": list(session.missing),
            "validation_errors": list(session.validation_errors or []),
            "session_duration_ms": int((time.time() - started) * 1000),
            "conversation_extra_tokens": 0,
            "workflow_extra_tokens": 0,
            "object_type": session.object_type,
        }
