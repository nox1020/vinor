from __future__ import annotations

import threading
from typing import Any

from app.self_reflection.di import make_reflection_engine
from app.self_reflection.engine import reflection_enabled
from app.self_reflection.interfaces import ReflectionEngine, ReflectionResult

_LOCK = threading.Lock()
_ENGINE: ReflectionEngine | None = None
_FALLBACK: dict[str, Any] = {}


def get_reflection_engine() -> ReflectionEngine | None:
    global _ENGINE
    if not reflection_enabled():
        return None
    if _ENGINE is not None:
        return _ENGINE
    with _LOCK:
        if _ENGINE is None:
            _ENGINE = make_reflection_engine()
    return _ENGINE


def run_reflection(
    *, analytics_row: dict[str, Any], shared: dict[str, Any] | None = None
) -> ReflectionResult | None:
    engine = get_reflection_engine()
    if engine is None:
        return None
    try:
        shared = dict(shared or {})
        result = engine.reflect(analytics_row=analytics_row, shared=shared)
        data = result.to_dict()
        global _FALLBACK
        _FALLBACK = data
        try:
            from flask import g, has_app_context, has_request_context

            if has_app_context() or has_request_context():
                g.ai_reflection = data
        except Exception:
            pass
        shared["reflection"] = data
        return result
    except Exception:
        return None


def get_reflection() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_reflection", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK)
