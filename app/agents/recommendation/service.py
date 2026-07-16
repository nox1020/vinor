from __future__ import annotations

import re
import threading
from typing import Any

from app.agents.recommendation.config import (
    recommendation_enabled,
    recommendation_inject_hint,
)
from app.agents.recommendation.di import make_recommendation_manager
from app.agents.recommendation.interfaces import (
    RecommendationManager,
    RecommendationRequest,
    RecommendationResult,
)

_LOCK = threading.Lock()
_MANAGER: RecommendationManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_HINT: str = ""

_RECOMMEND_RE = re.compile(
    r"(پیشنهاد|بهترین|مناسب.?من|توصیه|کدوم بخرم|کدام را بخرم|کدام بخرم|recommend)",
    re.I,
)


def get_recommendation_manager() -> RecommendationManager | None:
    global _MANAGER
    if not recommendation_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_recommendation_manager()
    return _MANAGER


def should_run_recommendation(*, route: str = "", message: str = "", chip_intent: str = "") -> bool:
    intent = (chip_intent or "").strip().lower()
    if intent in ("recommend", "suggestion", "best"):
        return True
    if _RECOMMEND_RE.search(message or ""):
        return True
    return False


def _store_obs(result: RecommendationResult | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_HINT
    if result is None:
        _FALLBACK_OBS = {}
        _FALLBACK_HINT = ""
        obs: dict[str, Any] = {}
        hint = ""
    else:
        hint = result.compact_hint if recommendation_inject_hint() else ""
        _FALLBACK_HINT = hint
        obs = {
            "recommendation_time_ms": int(result.recommendation_time_ms or 0),
            "recommendation_tokens": int(result.recommendation_tokens or 0),
            "recommendation_score": float(result.top_score or 0),
            "selected_property": str(result.selected_property or ""),
            "alternate_property": str(result.alternate_property or ""),
            "recommendation_cache_hit": bool(result.cache_hit),
            "recommendation_reuse_search": bool(result.reuse_search),
            "recommendation_reuse_analysis": bool(result.reuse_analysis),
            "recommendation_reuse_memory": bool(result.reuse_memory),
            "recommendation_reuse_planning": bool(result.reuse_planning),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_recommendation_obs = dict(obs)
            g.ai_recommendation_hint = hint
    except Exception:
        pass


def get_recommendation_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_recommendation_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "recommendation_time_ms": 0,
        "recommendation_tokens": 0,
        "recommendation_score": 0.0,
        "selected_property": "",
        "recommendation_cache_hit": False,
        "recommendation_reuse_search": False,
        "recommendation_reuse_analysis": False,
        "recommendation_reuse_memory": False,
    }


def get_recommendation_hint() -> str:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            return str(getattr(g, "ai_recommendation_hint", "") or "")
    except Exception:
        pass
    return _FALLBACK_HINT or ""


def clear_recommendation() -> None:
    _store_obs(None)


def run_recommendation(
    *,
    property_codes: list[str] | None = None,
    message: str = "",
    route: str = "",
    audience: str = "",
    user_key: str = "",
    shared: dict[str, Any] | None = None,
    analysis_categories: list[Any] | None = None,
    context_budget_chars: int = 90,
) -> RecommendationResult | None:
    manager = get_recommendation_manager()
    if manager is None:
        return None
    try:
        result = manager.run(
            RecommendationRequest(
                property_codes=tuple(property_codes or ()),
                message=message or "",
                route=route or "",
                audience=audience,
                user_key=user_key,
                shared=dict(shared or {}),
                analysis_categories=list(analysis_categories or []),
                context_budget_chars=int(context_budget_chars or 90),
            )
        )
        _store_obs(result)
        return result
    except Exception:
        return None
