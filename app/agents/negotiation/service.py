from __future__ import annotations

import re
import threading
from typing import Any

from app.agents.negotiation.config import negotiation_enabled, negotiation_inject_hint
from app.agents.negotiation.di import make_negotiation_manager
from app.agents.negotiation.interfaces import (
    NegotiationManager,
    NegotiationPlan,
    NegotiationRequest,
)

_LOCK = threading.Lock()
_MANAGER: NegotiationManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_HINT: str = ""
_FALLBACK_PLAN: dict[str, Any] = {}

_NEGOTIATION_RE = re.compile(
    r"(مذاکره|چانه|تخفیف|قیمت نهایی|پیشنهاد قیمت|negotiation|bargain|offer\s*price)",
    re.I,
)


def get_negotiation_manager() -> NegotiationManager | None:
    global _MANAGER
    if not negotiation_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_negotiation_manager()
    return _MANAGER


def should_run_negotiation(*, route: str = "", message: str = "", chip_intent: str = "") -> bool:
    intent = (chip_intent or "").strip().lower()
    if intent in ("negotiate", "negotiation", "bargain", "discount"):
        return True
    if _NEGOTIATION_RE.search(message or ""):
        return True
    return False


def _store_obs(plan: NegotiationPlan | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_HINT, _FALLBACK_PLAN
    if plan is None:
        _FALLBACK_OBS = {}
        _FALLBACK_HINT = ""
        _FALLBACK_PLAN = {}
        obs: dict[str, Any] = {}
        hint = ""
        pdata: dict[str, Any] = {}
    else:
        hint = plan.compact_hint if negotiation_inject_hint() else ""
        _FALLBACK_HINT = hint
        pdata = plan.to_dict()
        _FALLBACK_PLAN = pdata
        obs = {
            "negotiation_time_ms": int(plan.negotiation_time_ms or 0),
            "negotiation_tokens": int(plan.negotiation_tokens or 0),
            "negotiation_confidence": float(plan.confidence or 0),
            "negotiation_risk": float(plan.risk_score or 0),
            "negotiation_risk_level": str(plan.risk_level or ""),
            "deal_probability": float(plan.deal_probability or 0),
            "negotiation_strategy": str(plan.recommended_strategy or ""),
            "negotiation_cache_hit": bool(plan.cache_hit),
            "negotiation_reuse_analysis": bool(plan.reuse_analysis),
            "negotiation_reuse_recommendation": bool(plan.reuse_recommendation),
            "negotiation_reuse_customer_profile": bool(plan.reuse_customer_profile),
            "negotiation_reuse_workflow": bool(plan.reuse_workflow),
            "negotiation_reuse_planning": bool(plan.reuse_planning),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_negotiation_obs = dict(obs)
            g.ai_negotiation_hint = hint
            g.ai_negotiation_plan = pdata
    except Exception:
        pass


def get_negotiation_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_negotiation_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "negotiation_time_ms": 0,
        "negotiation_tokens": 0,
        "negotiation_confidence": 0.0,
        "negotiation_risk": 0.0,
        "deal_probability": 0.0,
        "negotiation_cache_hit": False,
        "negotiation_reuse_analysis": False,
        "negotiation_reuse_recommendation": False,
        "negotiation_reuse_customer_profile": False,
    }


def get_negotiation_hint() -> str:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            return str(getattr(g, "ai_negotiation_hint", "") or "")
    except Exception:
        pass
    return _FALLBACK_HINT or ""


def get_negotiation_plan() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_negotiation_plan", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_PLAN) if _FALLBACK_PLAN else {}


def clear_negotiation() -> None:
    _store_obs(None)


def run_negotiation(
    *,
    message: str = "",
    route: str = "",
    audience: str = "",
    user_key: str = "",
    shared: dict[str, Any] | None = None,
    context_budget_chars: int = 55,
) -> NegotiationPlan | None:
    manager = get_negotiation_manager()
    if manager is None:
        return None
    try:
        plan = manager.run(
            NegotiationRequest(
                message=message or "",
                route=route or "",
                audience=audience or "",
                user_key=user_key or "",
                shared=dict(shared or {}),
                context_budget_chars=int(context_budget_chars or 55),
            )
        )
        _store_obs(plan)
        return plan
    except Exception:
        return None
