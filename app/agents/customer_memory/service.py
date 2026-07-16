from __future__ import annotations

import re
import threading
from typing import Any

from app.agents.customer_memory.config import (
    customer_memory_enabled,
    customer_memory_inject_hint,
)
from app.agents.customer_memory.di import make_customer_memory_manager
from app.agents.customer_memory.interfaces import (
    CustomerMemoryManager,
    CustomerMemoryRequest,
    CustomerProfile,
)

_LOCK = threading.Lock()
_MANAGER: CustomerMemoryManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_HINT: str = ""
_FALLBACK_PROFILE: dict[str, Any] = {}

_PROFILE_RE = re.compile(
    r"(ترجیح|پروفایل|سابقه|بودجه.?من|چی دوست|سبک گفتگو|محدودیت|"
    r"رفتار مشتری|شناخت مشتری|customer.?profile|preferences?)",
    re.I,
)


def get_customer_memory_manager() -> CustomerMemoryManager | None:
    global _MANAGER
    if not customer_memory_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_customer_memory_manager()
    return _MANAGER


def should_run_customer_memory(*, route: str = "", message: str = "", chip_intent: str = "") -> bool:
    intent = (chip_intent or "").strip().lower()
    if intent in ("profile", "customer_memory", "prefs", "preferences"):
        return True
    if _PROFILE_RE.search(message or ""):
        return True
    return False


def _store_obs(profile: CustomerProfile | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_HINT, _FALLBACK_PROFILE
    if profile is None:
        _FALLBACK_OBS = {}
        _FALLBACK_HINT = ""
        _FALLBACK_PROFILE = {}
        obs: dict[str, Any] = {}
        hint = ""
        pdata: dict[str, Any] = {}
    else:
        hint = profile.compact_hint if customer_memory_inject_hint() else ""
        _FALLBACK_HINT = hint
        pdata = profile.to_dict()
        _FALLBACK_PROFILE = pdata
        obs = {
            "profile_build_time_ms": int(profile.profile_build_time_ms or 0),
            "relationship_score": float(profile.relationship_score or 0),
            "preference_count": int(profile.preference_count or 0),
            "profile_confidence": float(profile.confidence or 0),
            "customer_memory_tokens": int(profile.customer_memory_tokens or 0),
            "customer_memory_cache_hit": bool(profile.cache_hit),
            "customer_memory_reuse_memory": bool(profile.reuse_memory),
            "customer_memory_reuse_workflow": bool(profile.reuse_workflow),
            "customer_memory_reuse_recommendation": bool(profile.reuse_recommendation),
            "customer_memory_reuse_analysis": bool(profile.reuse_analysis),
            "customer_memory_reuse_planning": bool(profile.reuse_planning),
            "next_suggested_action": str(profile.next_suggested_action or ""),
            "interaction_style": str(profile.interaction_style or ""),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_customer_memory_obs = dict(obs)
            g.ai_customer_memory_hint = hint
            g.ai_customer_profile = pdata
    except Exception:
        pass


def get_customer_memory_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_customer_memory_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "profile_build_time_ms": 0,
        "relationship_score": 0.0,
        "preference_count": 0,
        "profile_confidence": 0.0,
        "customer_memory_tokens": 0,
        "customer_memory_cache_hit": False,
        "customer_memory_reuse_memory": False,
        "customer_memory_reuse_workflow": False,
        "customer_memory_reuse_recommendation": False,
    }


def get_customer_memory_hint() -> str:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            return str(getattr(g, "ai_customer_memory_hint", "") or "")
    except Exception:
        pass
    return _FALLBACK_HINT or ""


def get_customer_profile() -> dict[str, Any]:
    """Structured profile for Recommendation / Negotiation / Follow-up — outside Prompt."""
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_customer_profile", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_PROFILE) if _FALLBACK_PROFILE else {}


def clear_customer_memory() -> None:
    _store_obs(None)


def run_customer_memory(
    *,
    message: str = "",
    route: str = "",
    audience: str = "",
    user_key: str = "",
    shared: dict[str, Any] | None = None,
    context_budget_chars: int = 70,
) -> CustomerProfile | None:
    manager = get_customer_memory_manager()
    if manager is None:
        return None
    try:
        shared = dict(shared or {})
        shared.setdefault("audience", audience)
        profile = manager.build(
            CustomerMemoryRequest(
                user_key=user_key or "",
                message=message or "",
                route=route or "",
                audience=audience or "",
                shared=shared,
                context_budget_chars=int(context_budget_chars or 70),
            )
        )
        _store_obs(profile)
        return profile
    except Exception:
        return None
