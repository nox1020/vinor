from __future__ import annotations

import threading
from typing import Any

from app.self_learning.config import self_learning_enabled
from app.self_learning.di import make_learning_manager
from app.self_learning.interfaces import LearningManager, LearningReport

_LOCK = threading.Lock()
_MANAGER: LearningManager | None = None
_FALLBACK: dict[str, Any] = {}


def get_learning_manager() -> LearningManager | None:
    global _MANAGER
    if not self_learning_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_learning_manager()
    return _MANAGER


def run_self_learning(records: list[dict[str, Any]] | None = None) -> LearningReport | None:
    """Background/manual — not request-path critical."""
    manager = get_learning_manager()
    if manager is None:
        return None
    try:
        report = manager.learn(records)
        global _FALLBACK
        _FALLBACK = report.to_dict()
        return report
    except Exception:
        return None


def get_learning_report() -> dict[str, Any]:
    return dict(_FALLBACK)
