"""Continuous Optimization Engine (Phase 19) — background recommendations only."""

from app.optimization.di import make_optimization_manager
from app.optimization.service import (
    get_latest_optimization_report,
    list_reports_for_admin,
    run_optimization,
)

__all__ = [
    "make_optimization_manager",
    "run_optimization",
    "get_latest_optimization_report",
    "list_reports_for_admin",
]
