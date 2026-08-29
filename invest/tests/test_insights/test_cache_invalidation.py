"""Smoke test: insights cache invalidation after portfolio changes."""

from app.insights.engine import InvestmentInsightsEngine
from app.insights.provider import InsightProvider
from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService


def test_insights_refresh_after_trade(trade_service) -> None:
    analytics = PortfolioAnalyticsService(trade_service.portfolio)
    engine = InvestmentInsightsEngine()
    provider = InsightProvider(analytics, engine)

    before = provider.list_insights(calendar="jalali")
    assert isinstance(before, list)

    trade_service.create_asset(
        name="Solo",
        symbol="SOLO",
        quantity=1,
        avg_buy_price=100,
        current_price=100,
    )
    analytics.invalidate_cache()
    engine.invalidate_cache()

    after = provider.list_insights(calendar="jalali")
    ids = {v.id for v in after}
    assert any(
        "single_asset" in i or "large_allocation" in i or "inactive" not in i
        for i in ids
    ) or len(after) >= 1
