from __future__ import annotations

import threading
from typing import Any

from app.long_planner.config import long_planner_enabled
from app.long_planner.di import make_long_planner_manager
from app.long_planner.interfaces import LongPlannerManager, PlanGraph

_LOCK = threading.Lock()
_MANAGER: LongPlannerManager | None = None
_FALLBACK: dict[str, Any] = {}


def get_long_planner_manager() -> LongPlannerManager | None:
    global _MANAGER
    if not long_planner_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_long_planner_manager()
    return _MANAGER


def _store(graph: PlanGraph | None) -> None:
    global _FALLBACK
    data = graph.to_dict() if graph else {}
    _FALLBACK = data
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_long_plan = data
    except Exception:
        pass


def get_long_plan() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_long_plan", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK)


def build_long_plan(*, shared: dict[str, Any] | None = None, route: str = "") -> PlanGraph | None:
    manager = get_long_planner_manager()
    if manager is None:
        return None
    try:
        shared = dict(shared or {})
        try:
            from flask import g, has_app_context, has_request_context

            if has_app_context() or has_request_context():
                if not shared.get("goals"):
                    shared["goals"] = getattr(g, "ai_goals", None) or {}
                if not shared.get("world_model"):
                    shared["world_model"] = getattr(g, "ai_world_model", None) or {}
        except Exception:
            pass
        graph = manager.build(shared=shared, route=route)
        _store(graph)
        shared["long_plan"] = graph.to_dict()
        return graph
    except Exception:
        return None
