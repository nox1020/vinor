"""AI Evaluation & Observability Platform (Phase 17.5) — monitoring only, 0% prompt tokens."""

from app.evaluation.di import make_evaluation_manager
from app.evaluation.service import get_analytics_summary, record_evaluation

__all__ = ["make_evaluation_manager", "record_evaluation", "get_analytics_summary"]
