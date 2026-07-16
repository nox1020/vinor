from __future__ import annotations

from app.self_reflection.engine import RuleReflectionEngine
from app.self_reflection.interfaces import ReflectionEngine


def make_reflection_engine() -> ReflectionEngine:
    return RuleReflectionEngine()
