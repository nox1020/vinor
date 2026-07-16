from __future__ import annotations

import threading
from typing import Any

from app.self_improvement.di import make_improvement_manager
from app.self_improvement.interfaces import ImprovementManager, ImprovementReport
from app.self_improvement.manager import self_improvement_enabled

_LOCK = threading.Lock()
_MANAGER: ImprovementManager | None = None
_FALLBACK: dict[str, Any] = {}


def get_improvement_manager() -> ImprovementManager | None:
    global _MANAGER
    if not self_improvement_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_improvement_manager()
    return _MANAGER


def run_self_improvement(
    *,
    reflection: dict[str, Any] | None = None,
    learning: dict[str, Any] | None = None,
) -> ImprovementReport | None:
    manager = get_improvement_manager()
    if manager is None:
        return None
    try:
        if reflection is None:
            try:
                from app.self_reflection.service import get_reflection

                reflection = get_reflection()
            except Exception:
                reflection = {}
        if learning is None:
            try:
                from app.self_learning.service import get_learning_report

                learning = get_learning_report()
            except Exception:
                learning = {}
        report = manager.improve(reflection=reflection or {}, learning=learning or {})
        global _FALLBACK
        _FALLBACK = report.to_dict()
        return report
    except Exception:
        return None
