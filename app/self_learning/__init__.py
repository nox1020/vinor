"""Self Learning Engine (Phase 23) — rule-based patterns, no fine-tune/prompt."""

from app.self_learning.di import make_learning_manager
from app.self_learning.service import run_self_learning

__all__ = ["make_learning_manager", "run_self_learning"]
