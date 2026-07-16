from __future__ import annotations

import threading
from typing import Any

from app.conversation.config import conversation_enabled
from app.conversation.di import make_conversation_manager
from app.conversation.interfaces import ConversationManager, ConversationOutcome

_LOCK = threading.Lock()
_MANAGER: ConversationManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}


def get_conversation_manager() -> ConversationManager | None:
    global _MANAGER
    if not conversation_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_conversation_manager()
    return _MANAGER


def _store_obs(obs: dict[str, Any] | None) -> None:
    global _FALLBACK_OBS
    _FALLBACK_OBS = dict(obs or {})
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_conversation_obs = dict(_FALLBACK_OBS)
            if obs and obs.get("structured_object"):
                g.ai_conversation_object = obs.get("structured_object")
    except Exception:
        pass


def get_conversation_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_conversation_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "detected_role": "",
        "detected_intent": "",
        "workflow": "",
        "workflow_name": "",
        "workflow_state": "",
        "conversation_state": "",
        "current_step": "",
        "completed_fields": [],
        "completed_steps": [],
        "missing_fields": [],
        "missing_steps": [],
        "validation_errors": [],
        "conversation_extra_tokens": 0,
        "workflow_extra_tokens": 0,
    }


def try_conversation_engine(
    *,
    message: str,
    user_key: str,
    audience: str,
    voice: str = "",
    chip_intent: str = "",
    thread_id: str | None = None,
) -> dict[str, Any] | None:
    """Fail-open public API for generate_reply — before Supervisor."""
    manager = get_conversation_manager()
    if manager is None:
        return None
    try:
        out: ConversationOutcome = manager.handle(
            message=message or "",
            user_key=user_key or "",
            audience=audience or "",
            voice=voice,
            chip_intent=chip_intent or "",
            thread_id=thread_id,
        )
        obs = dict(out.observability or {})
        if out.structured_object:
            obs["structured_object"] = out.structured_object
        _store_obs(obs)

        if not out.handled:
            return {
                "ok": True,
                "handled": False,
                "pass_to_supervisor": True,
                "observability": obs,
            }

        # Active form step — return chat reply without Supervisor/LLM.
        if out.handled and not out.pass_to_supervisor:
            return {
                "ok": True,
                "handled": True,
                "reply": out.reply or "",
                "land_codes": [],
                "land_cards": [],
                "agent_actions": [],
                "meta": {"provider": "conversation_engine"},
                "observability": obs,
            }

        # Completed object — continue to Supervisor with object on g.
        if out.structured_object:
            try:
                from flask import g, has_app_context, has_request_context

                if has_app_context() or has_request_context():
                    g.ai_conversation_object = out.structured_object
            except Exception:
                pass
            return {
                "ok": True,
                "handled": True,
                "pass_to_supervisor": True,
                "reply": out.reply or "",
                "structured_object": out.structured_object,
                "observability": obs,
            }

        return {
            "ok": True,
            "handled": out.handled,
            "pass_to_supervisor": out.pass_to_supervisor,
            "reply": out.reply or "",
            "observability": obs,
        }
    except Exception:
        return None
