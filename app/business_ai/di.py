from __future__ import annotations

from app.business_ai.engine import RuleAutonomousBusinessAI
from app.business_ai.interfaces import AutonomousBusinessAI


def make_business_ai() -> AutonomousBusinessAI:
    return RuleAutonomousBusinessAI()
