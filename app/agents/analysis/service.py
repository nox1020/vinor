from __future__ import annotations

import threading
from typing import Any

from app.agents.analysis.config import analysis_enabled, analysis_inject_hint
from app.agents.analysis.di import make_analysis_manager
from app.agents.analysis.interfaces import AnalysisManager, AnalysisRequest, AnalysisResult

_LOCK = threading.Lock()
_MANAGER: AnalysisManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_HINT: str = ""


def get_analysis_manager() -> AnalysisManager | None:
    global _MANAGER
    if not analysis_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_analysis_manager()
    return _MANAGER


def _store_obs(result: AnalysisResult | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_HINT
    if result is None:
        _FALLBACK_OBS = {}
        _FALLBACK_HINT = ""
        obs: dict[str, Any] = {}
        hint = ""
    else:
        hint = result.compact_hint if analysis_inject_hint() else ""
        _FALLBACK_HINT = hint
        obs = {
            "analysis_time_ms": int(result.analysis_time_ms or 0),
            "analysis_tokens": int(result.analysis_tokens or 0),
            "analysis_cache_hit": bool(result.cache_hit),
            "analysis_reused_context": bool(result.reused_context),
            "analysis_reused_rag": bool(result.reused_rag),
            "analysis_reused_memory": bool(result.reused_memory),
            "analysis_reused_planning": bool(result.reused_planning),
            "analysis_codes": list(result.property_codes or []),
            "analysis_ok": bool(result.ok),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_analysis_obs = dict(obs)
            g.ai_analysis_hint = hint
    except Exception:
        pass


def get_analysis_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_analysis_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "analysis_time_ms": 0,
        "analysis_tokens": 0,
        "analysis_cache_hit": False,
        "analysis_reused_context": False,
        "analysis_reused_rag": False,
        "analysis_reused_memory": False,
        "analysis_reused_planning": False,
        "analysis_codes": [],
    }


def get_analysis_hint() -> str:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            return str(getattr(g, "ai_analysis_hint", "") or "")
    except Exception:
        pass
    return _FALLBACK_HINT or ""


def clear_analysis() -> None:
    _store_obs(None)


def run_property_analysis(
    *,
    property_codes: list[str] | None = None,
    message: str = "",
    route: str = "",
    audience: str = "",
    user_key: str = "",
    shared: dict[str, Any] | None = None,
    context_budget_chars: int = 100,
) -> AnalysisResult | None:
    manager = get_analysis_manager()
    if manager is None:
        return None
    try:
        result = manager.run(
            AnalysisRequest(
                property_codes=tuple(property_codes or ()),
                message=message or "",
                route=route or "",
                audience=audience,
                user_key=user_key,
                shared=dict(shared or {}),
                context_budget_chars=int(context_budget_chars or 100),
            )
        )
        _store_obs(result)
        return result
    except Exception:
        return None


def should_run_analysis(*, route: str = "", message: str = "", chip_intent: str = "") -> bool:
    """Supervisor-driven lazy gate — compare route or analysis keywords."""
    route = (route or "").strip()
    if route in ("property_compare",):
        return True
    msg = (message or "").strip()
    intent = (chip_intent or "").strip().lower()
    if intent in ("analyze", "compare", "analysis"):
        return True
    import re

    if re.search(
        r"(تحلیل|مقایسه|ارزش خرید|سرمایه.?گذار|مزایا|معایب|کدام بهتر|فرق)",
        msg,
        re.I,
    ):
        return True
    return False
