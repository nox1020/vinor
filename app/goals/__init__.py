"""Autonomous Goal Engine (Phase 20) — Goal objects only, no prompt/hint."""

from app.goals.di import make_goal_manager
from app.goals.service import get_goals, run_goals

__all__ = ["make_goal_manager", "run_goals", "get_goals"]
