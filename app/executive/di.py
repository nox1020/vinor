from __future__ import annotations

from app.executive.engine import RuleExecutiveAI
from app.executive.interfaces import ExecutiveAI


def make_executive_ai() -> ExecutiveAI:
    return RuleExecutiveAI()
