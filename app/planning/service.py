from __future__ import annotations

import threading

from app.planning.config import planning_enabled
from app.planning.di import make_planning_manager
from app.planning.interfaces import PlanningManager, PlanningOutcome, PlanningRequest

_LOCK = threading.Lock()
_MANAGER: PlanningManager | None = None


def get_planning_manager() -> PlanningManager | None:
    global _MANAGER
    if not planning_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_planning_manager()
    return _MANAGER


def run_planning_once(
    *,
    goal: str,
    user_key: str = "",
    audience: str = "",
    voice: str = "",
    thread_id: str | None = None,
    chip_intent: str = "",
) -> PlanningOutcome | None:
    manager = get_planning_manager()
    if manager is None:
        return None
    try:
        return manager.run_once(
            PlanningRequest(
                goal=goal or "",
                user_key=user_key,
                audience=audience,
                voice=voice,
                thread_id=thread_id,
                chip_intent=chip_intent or "",
            )
        )
    except Exception:
        return None
