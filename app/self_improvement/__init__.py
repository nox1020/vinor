"""Self Improvement Engine (Phase 25) — suggestions only, never auto-apply."""

from app.self_improvement.di import make_improvement_manager
from app.self_improvement.service import run_self_improvement

__all__ = ["make_improvement_manager", "run_self_improvement"]
