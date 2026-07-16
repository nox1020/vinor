from __future__ import annotations

from app.self_improvement.interfaces import ImprovementManager
from app.self_improvement.manager import RuleImprovementManager


def make_improvement_manager() -> ImprovementManager:
    return RuleImprovementManager()
