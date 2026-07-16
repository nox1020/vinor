from __future__ import annotations

from app.self_learning.extractor import RulePatternExtractor
from app.self_learning.interfaces import LearningManager
from app.self_learning.manager import DefaultLearningManager


def make_learning_manager() -> LearningManager:
    return DefaultLearningManager(extractor=RulePatternExtractor())
