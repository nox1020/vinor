from __future__ import annotations

import threading
from typing import Any

from app.supervisor.config import supervisor_enabled
from app.supervisor.di import make_supervisor_manager
from app.supervisor.interfaces import (
    ComponentFlags,
    SupervisorManager,
    SupervisorOutcome,
    SupervisorRequest,
    Workflow,
)

_LOCK = threading.Lock()
_MANAGER: SupervisorManager | None = None
_FALLBACK_WORKFLOW: Workflow | None = None
_FALLBACK_OBS: dict[str, Any] = {}


def get_supervisor_manager() -> SupervisorManager | None:
    global _MANAGER
    if not supervisor_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_supervisor_manager()
    return _MANAGER


def orchestrate_request(
    *,
    message: str,
    audience: str = "",
    voice: str = "",
    chip_intent: str = "",
    user_key: str = "",
) -> SupervisorOutcome | None:
    manager = get_supervisor_manager()
    if manager is None:
        return None
    try:
        return manager.orchestrate(
            SupervisorRequest(
                message=message or "",
                audience=audience,
                voice=voice,
                chip_intent=chip_intent or "",
                user_key=user_key,
            )
        )
    except Exception:
        return None


def current_workflow() -> Workflow | None:
    global _FALLBACK_WORKFLOW
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            wf = getattr(g, "ai_supervisor_workflow", None)
            if isinstance(wf, Workflow):
                return wf
    except Exception:
        pass
    return _FALLBACK_WORKFLOW


def current_flags() -> ComponentFlags | None:
    wf = current_workflow()
    return wf.flags if wf else None


def allow_component(name: str, *, default: bool = True) -> bool:
    """Lazy gate used by Memory/Planning/RAG bridges — does not rewrite those layers."""
    flags = current_flags()
    if flags is None:
        return default
    mapping = {
        "planning": flags.use_planning,
        "memory": flags.use_memory,
        "rag": flags.use_rag,
        "tools": flags.use_tools,
        "llm": flags.use_llm,
    }
    return bool(mapping.get(name, default))


def set_supervisor_context(outcome: SupervisorOutcome | None) -> None:
    global _FALLBACK_WORKFLOW, _FALLBACK_OBS
    if outcome is None:
        _FALLBACK_WORKFLOW = None
        _FALLBACK_OBS = {}
        obs: dict[str, Any] = {}
        wf = None
    else:
        _FALLBACK_WORKFLOW = outcome.workflow
        obs = {
            "routed_workflow": outcome.workflow.route,
            "executed_components": list(outcome.workflow.executed),
            "skipped_components": list(outcome.workflow.skipped),
            "routing_time_ms": int(outcome.routing_time_ms or 0),
            "context_budget_chars": int(outcome.workflow.flags.context_budget_chars or 0),
        }
        _FALLBACK_OBS = dict(obs)
        wf = outcome.workflow
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_supervisor_workflow = wf
            g.ai_supervisor_obs = dict(obs)
    except Exception:
        pass


def get_supervisor_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_supervisor_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    if _FALLBACK_OBS:
        return dict(_FALLBACK_OBS)
    return {
        "routed_workflow": "",
        "executed_components": [],
        "skipped_components": [],
        "routing_time_ms": 0,
        "context_budget_chars": 0,
    }
