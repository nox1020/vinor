"""Professional reports built from analytics."""

from __future__ import annotations

from app.analytics.models import (
    AssetReport,
    PerformanceReport,
    PortfolioSummaryReport,
    TaxReportStub,
    TradeReport,
)
from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from app.utils.dates import now_iso


class AnalyticsReportGenerator:
    """Report generator — all sections sourced from PortfolioAnalyticsService."""

    def __init__(self, analytics: PortfolioAnalyticsService) -> None:
        self._analytics = analytics

    def portfolio_summary(self, *, calendar: str) -> PortfolioSummaryReport:
        bundle = self._analytics.analyze(calendar=calendar)
        return PortfolioSummaryReport(
            capital=bundle.capital,
            trades=bundle.trades,
            generated_at=now_iso(),
        )

    def asset_report(self, *, calendar: str) -> AssetReport:
        bundle = self._analytics.analyze(calendar=calendar)
        return AssetReport(rows=bundle.assets, calendar=calendar)

    def trade_report(self, *, calendar: str) -> TradeReport:
        bundle = self._analytics.analyze(calendar=calendar)
        return TradeReport(
            analytics=bundle.trades,
            closed_count=bundle.trades.closed_trades,
        )

    def performance_report(self, *, calendar: str) -> PerformanceReport:
        bundle = self._analytics.analyze(calendar=calendar)
        return PerformanceReport(
            periods=bundle.periods,
            growth_series=bundle.growth_series,
            calendar=calendar,
        )

    def monthly_report(self, *, calendar: str) -> PerformanceReport:
        bundle = self._analytics.analyze(calendar=calendar)
        return PerformanceReport(
            periods={"monthly": bundle.periods.get("monthly", [])},
            growth_series=bundle.growth_series,
            calendar=calendar,
        )

    def yearly_report(self, *, calendar: str) -> PerformanceReport:
        bundle = self._analytics.analyze(calendar=calendar)
        return PerformanceReport(
            periods={"yearly": bundle.periods.get("yearly", [])},
            growth_series=bundle.growth_series,
            calendar=calendar,
        )

    def tax_report_stub(self, *, calendar: str) -> TaxReportStub:
        return TaxReportStub(calendar=calendar)
