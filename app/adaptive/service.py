from __future__ import annotations

import threading
from typing import Any

from app.adaptive.config import adaptive_enabled
from app.adaptive.controller import DefaultAdaptiveController
from app.adaptive.di import make_adaptive_controller
from app.adaptive.interfaces import (
    AdaptiveController,
    AdaptiveOutcome,
    AdaptiveRequest,
    WorkflowState,
)

_LOCK = threading.Lock()
_CONTROLLER: AdaptiveController | None = None
_FALLBACK_WF: WorkflowState | None = None
_FALLBACK_OBS: dict[str, Any] = {}


def get_adaptive_controller() -> AdaptiveController | None:
    global _CONTROLLER
    if not adaptive_enabled():
        return None
    if _CONTROLLER is not None:
        return _CONTROLLER
    with _LOCK:
        if _CONTROLLER is None:
            _CONTROLLER = make_adaptive_controller()
    return _CONTROLLER


def _store(outcome: AdaptiveOutcome | None) -> None:
    global _FALLBACK_WF, _FALLBACK_OBS
    if outcome is None:
        _FALLBACK_WF = None
        _FALLBACK_OBS = {}
        obs: dict[str, Any] = {}
        wf = None
    else:
        wf = outcome.workflow
        _FALLBACK_WF = wf
        q = wf.quality
        obs = {
            "workflow_state": wf.state,
            "workflow_route": wf.route,
            "confidence_score": float(wf.confidence.value),
            "confidence_reason": wf.confidence.reason,
            "retry_count": int(wf.retry_count),
            "recovery_count": int(wf.recovery_count),
            "skipped_steps": list(wf.skipped_steps),
            "workflow_strategy": wf.strategy,
            "workflow_history": list(wf.history),
            "quality_complete": bool(q.complete) if q else None,
            "quality_found_suitable": bool(q.found_suitable) if q else None,
            "quality_needs_continue": bool(q.needs_continue) if q else None,
            "adaptive_extra_tokens": int(outcome.extra_tokens),
            "adaptive_time_ms": int(outcome.execution_time_ms),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_adaptive_workflow = wf
            g.ai_adaptive_obs = dict(obs)
    except Exception:
        pass


def current_workflow() -> WorkflowState | None:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            wf = getattr(g, "ai_adaptive_workflow", None)
            if isinstance(wf, WorkflowState):
                return wf
    except Exception:
        pass
    return _FALLBACK_WF


def get_adaptive_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_adaptive_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    if _FALLBACK_OBS:
        return dict(_FALLBACK_OBS)
    return {
        "workflow_state": "",
        "confidence_score": 0.0,
        "retry_count": 0,
        "recovery_count": 0,
        "skipped_steps": [],
        "adaptive_extra_tokens": 0,
    }


def use_lean_strategy() -> bool:
    """Caller flag: on retry, skip planning hint/seed (no new prompt content)."""
    return DefaultAdaptiveController.lean_strategy(current_workflow())


def begin_adaptive(
    *,
    message: str,
    route: str = "",
    audience: str = "",
    voice: str = "",
    chip_intent: str = "",
    user_key: str = "",
) -> AdaptiveOutcome | None:
    ctrl = get_adaptive_controller()
    if ctrl is None:
        _store(None)
        return None
    try:
        out = ctrl.begin(
            AdaptiveRequest(
                message=message or "",
                route=route or "",
                audience=audience,
                voice=voice,
                chip_intent=chip_intent or "",
                user_key=user_key,
            )
        )
        _store(out)
        return out
    except Exception:
        _store(None)
        return None


def after_agent_prepare_adaptive(
    *,
    agent_status: str = "",
    used_components: list[str] | None = None,
    selected_agent: str = "",
) -> AdaptiveOutcome | None:
    ctrl = get_adaptive_controller()
    wf = current_workflow()
    if ctrl is None or wf is None:
        return None
    try:
        out = ctrl.after_agent_prepare(
            wf,
            agent_status=agent_status or "",
            used_components=list(used_components or []),
            selected_agent=selected_agent or "",
        )
        _store(out)
        return out
    except Exception:
        return None


def after_response_adaptive(
    *,
    reply: str = "",
    land_codes: list[str] | None = None,
    ok: bool = True,
) -> AdaptiveOutcome | None:
    ctrl = get_adaptive_controller()
    wf = current_workflow()
    if ctrl is None or wf is None:
        return None
    try:
        out = ctrl.after_response(
            wf,
            reply=reply or "",
            land_codes=list(land_codes or []),
            ok=ok,
        )
        _store(out)
        return out
    except Exception:
        return None


def fail_adaptive(*, error: str = "") -> AdaptiveOutcome | None:
    ctrl = get_adaptive_controller()
    wf = current_workflow()
    if ctrl is None or wf is None:
        return None
    try:
        out = ctrl.on_failure(wf, error=error or "")
        _store(out)
        return out
    except Exception:
        return None


def clear_adaptive() -> None:
    _store(None)
