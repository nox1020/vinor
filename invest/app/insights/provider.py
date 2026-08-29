"""UI-facing insight provider (no calculations in the UI)."""

from __future__ import annotations

from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from app.insights.categories import InsightCategory
from app.insights.engine import InvestmentInsightsEngine
from app.insights.formatter import format_insight_for_ui
from app.insights.models import Insight, InsightBundle, InsightViewModel
from app.insights.severity import InsightSeverity


class InsightProvider:
    """
    Produce sorted, presentation-ready insights from analytics.

    UI should only call ``list_insights`` / ``get_bundle`` — never run rules.
    """

    def __init__(
        self,
        analytics: PortfolioAnalyticsService,
        engine: InvestmentInsightsEngine | None = None,
    ) -> None:
        self._analytics = analytics
        self._engine = engine or InvestmentInsightsEngine()
        self._goal_roi_pct: float | None = None

    @property
    def engine(self) -> InvestmentInsightsEngine:
        return self._engine

    def set_goal_roi_pct(self, value: float | None) -> None:
        """Inject user goal into analytics fingerprint (from settings)."""
        self._goal_roi_pct = value

    def invalidate(self) -> None:
        self._analytics.invalidate_cache()
        self._engine.invalidate_cache()

    def get_bundle(self, *, calendar: str) -> InsightBundle:
        analytics_bundle = self._analytics.analyze(
            calendar=calendar,
            goal_roi_pct=self._goal_roi_pct,
        )
        return self._engine.generate(analytics_bundle)

    def list_insights(
        self,
        *,
        calendar: str,
        category: InsightCategory | None = None,
        min_severity: InsightSeverity | None = None,
        limit: int | None = None,
    ) -> list[InsightViewModel]:
        bundle = self.get_bundle(calendar=calendar)
        items: list[Insight] = list(bundle.insights)
        if category is not None:
            items = [i for i in items if i.category == category]
        if min_severity is not None:
            items = [i for i in items if i.severity >= min_severity]
        if limit is not None:
            items = items[:limit]
        return [format_insight_for_ui(i) for i in items]
