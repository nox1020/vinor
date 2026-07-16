from __future__ import annotations

import threading
from typing import Any

from app.decision.config import decision_enabled, decision_inject_hint
from app.decision.di import make_decision_manager
from app.decision.interfaces import DecisionManager, DecisionRequest, DecisionResult

_LOCK = threading.Lock()
_MANAGER: DecisionManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_HINT: str = ""
_FALLBACK_DECISION: dict[str, Any] = {}


def get_decision_manager() -> DecisionManager | None:
    global _MANAGER
    if not decision_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_decision_manager()
    return _MANAGER


def _store_obs(result: DecisionResult | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_HINT, _FALLBACK_DECISION
    if result is None:
        _FALLBACK_OBS = {}
        _FALLBACK_HINT = ""
        _FALLBACK_DECISION = {}
        obs: dict[str, Any] = {}
        hint = ""
        data: dict[str, Any] = {}
    else:
        hint = result.compact_hint if decision_inject_hint() else ""
        _FALLBACK_HINT = hint
        data = result.to_dict()
        _FALLBACK_DECISION = data
        obs = {
            "decision_time_ms": int(result.decision_time_ms or 0),
            "decision_score": float(result.decision_score or 0),
            "decision_confidence": float(result.confidence or 0),
            "conflict_count": int(result.conflict_count or 0),
            "alternative_count": len(result.alternative_properties or []),
            "selected_property": str(result.selected_property or ""),
            "decision_tokens": int(result.decision_tokens or 0),
            "conflict_resolve_time_ms": int(result.conflict_resolve_time_ms or 0),
            "next_step": str(result.next_step or ""),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_decision_obs = dict(obs)
            g.ai_decision_hint = hint
            g.ai_decision = data
    except Exception:
        pass


def get_decision_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_decision_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "decision_time_ms": 0,
        "decision_score": 0.0,
        "decision_confidence": 0.0,
        "conflict_count": 0,
        "alternative_count": 0,
        "selected_property": "",
        "decision_tokens": 0,
        "conflict_resolve_time_ms": 0,
    }


def get_decision_hint() -> str:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            return str(getattr(g, "ai_decision_hint", "") or "")
    except Exception:
        pass
    return _FALLBACK_HINT or ""


def get_decision() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_decision", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_DECISION) if _FALLBACK_DECISION else {}


def clear_decision() -> None:
    _store_obs(None)


def run_decision(
    *,
    message: str = "",
    route: str = "",
    shared: dict[str, Any] | None = None,
    parallel_merge: dict[str, Any] | None = None,
) -> DecisionResult | None:
    """Fail-open public API — never re-runs agents."""
    manager = get_decision_manager()
    if manager is None:
        return None
    try:
        shared = dict(shared or {})
        # Soft-pull structured objects already on g (reuse only).
        try:
            from flask import g, has_app_context, has_request_context

            if has_app_context() or has_request_context():
                if not shared.get("customer_profile"):
                    shared["customer_profile"] = getattr(g, "ai_customer_profile", None) or {}
                if not shared.get("negotiation_plan"):
                    shared["negotiation_plan"] = getattr(g, "ai_negotiation_plan", None) or {}
                if not shared.get("customer_success"):
                    shared["customer_success"] = getattr(g, "ai_customer_success", None) or {}
                if not parallel_merge:
                    parallel_merge = getattr(g, "ai_parallel_merge", None) or {}
        except Exception:
            pass

        result = manager.run(
            DecisionRequest(
                message=message or "",
                route=route or "",
                shared=shared,
                parallel_merge=dict(parallel_merge or {}),
            )
        )
        _store_obs(result)
        try:
            shared["decision"] = result.to_dict()
        except Exception:
            pass
        return result
    except Exception:
        return None
