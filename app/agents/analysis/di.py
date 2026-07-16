from __future__ import annotations

from app.agents.analysis.cache import MemoryAnalysisCache
from app.agents.analysis.interfaces import AnalysisManager
from app.agents.analysis.manager import DefaultAnalysisManager
from app.agents.analysis.strategy import RuleAnalysisStrategy


def make_analysis_manager() -> AnalysisManager:
    return DefaultAnalysisManager(
        strategy=RuleAnalysisStrategy(),
        cache=MemoryAnalysisCache(),
    )
