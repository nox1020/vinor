from __future__ import annotations

import re
import threading
from typing import Any

from app.agents.customer_success.config import (
    customer_success_enabled,
    customer_success_inject_hint,
)
from app.agents.customer_success.di import make_customer_success_manager
from app.agents.customer_success.interfaces import (
    CustomerSuccessManager,
    CustomerSuccessPlan,
    CustomerSuccessRequest,
)

_LOCK = threading.Lock()
_MANAGER: CustomerSuccessManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_HINT: str = ""
_FALLBACK_PLAN: dict[str, Any] = {}

_SUCCESS_RE = re.compile(
    r"(پیگیری|فالو.?آپ|follow.?up|اقدام بعدی|بعدا تماس|یادآوری|"
    r"چرخه مشتری|customer.?success|مرحله مشتری)",
    re.I,
)


def get_customer_success_manager() -> CustomerSuccessManager | None:
    global _MANAGER
    if not customer_success_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_customer_success_manager()
    return _MANAGER


def should_run_customer_success(*, route: str = "", message: str = "", chip_intent: str = "") -> bool:
    intent = (chip_intent or "").strip().lower()
    if intent in ("follow_up", "followup", "customer_success", "nurture", "reminder"):
        return True
    if _SUCCESS_RE.search(message or ""):
        return True
    return False


def _store_obs(plan: CustomerSuccessPlan | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_HINT, _FALLBACK_PLAN
    if plan is None:
        _FALLBACK_OBS = {}
        _FALLBACK_HINT = ""
        _FALLBACK_PLAN = {}
        obs: dict[str, Any] = {}
        hint = ""
        pdata: dict[str, Any] = {}
    else:
        hint = plan.compact_hint if customer_success_inject_hint() else ""
        _FALLBACK_HINT = hint
        pdata = plan.to_dict()
        _FALLBACK_PLAN = pdata
        obs = {
            "customer_success_time_ms": int(plan.build_time_ms or 0),
            "customer_success_tokens": int(plan.customer_success_tokens or 0),
            "customer_stage": str(plan.customer_stage or ""),
            "conversion_probability": float(plan.conversion_probability or 0),
            "next_action": str(plan.next_action or ""),
            "priority": str(plan.priority or ""),
            "customer_success_confidence": float(plan.confidence or 0),
            "followup_type": str(plan.followup_type or ""),
            "followup_time": str(plan.followup_time or ""),
            "customer_success_cache_hit": bool(plan.cache_hit),
            "customer_success_reuse_analysis": bool(plan.reuse_analysis),
            "customer_success_reuse_recommendation": bool(plan.reuse_recommendation),
            "customer_success_reuse_negotiation": bool(plan.reuse_negotiation),
            "customer_success_reuse_customer_profile": bool(plan.reuse_customer_profile),
            "customer_success_reuse_workflow": bool(plan.reuse_workflow),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_customer_success_obs = dict(obs)
            g.ai_customer_success_hint = hint
            g.ai_customer_success = pdata
    except Exception:
        pass


def get_customer_success_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_customer_success_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "customer_success_time_ms": 0,
        "customer_success_tokens": 0,
        "customer_stage": "",
        "conversion_probability": 0.0,
        "next_action": "",
        "priority": "",
        "customer_success_confidence": 0.0,
        "customer_success_cache_hit": False,
        "customer_success_reuse_analysis": False,
        "customer_success_reuse_recommendation": False,
        "customer_success_reuse_negotiation": False,
        "customer_success_reuse_customer_profile": False,
    }


def get_customer_success_hint() -> str:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            return str(getattr(g, "ai_customer_success_hint", "") or "")
    except Exception:
        pass
    return _FALLBACK_HINT or ""


def get_customer_success_plan() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_customer_success", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_PLAN) if _FALLBACK_PLAN else {}


def clear_customer_success() -> None:
    _store_obs(None)


def run_customer_success(
    *,
    message: str = "",
    route: str = "",
    audience: str = "",
    user_key: str = "",
    shared: dict[str, Any] | None = None,
    context_budget_chars: int = 55,
) -> CustomerSuccessPlan | None:
    manager = get_customer_success_manager()
    if manager is None:
        return None
    try:
        plan = manager.run(
            CustomerSuccessRequest(
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
