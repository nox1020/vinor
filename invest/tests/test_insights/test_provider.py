"""Integration: insights via analytics service."""

from app.insights.provider import InsightProvider
from app.insights.engine import InvestmentInsightsEngine
from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService


def test_provider_list_insights(trade_service) -> None:
    trade_service.create_asset(
        name="Gold",
        symbol="GOLD",
        quantity=10,
        avg_buy_price=1000,
        current_price=1000,
    )
    analytics = PortfolioAnalyticsService(trade_service.portfolio)
    provider = InsightProvider(analytics, InvestmentInsightsEngine())
    views = provider.list_insights(calendar="jalali")
    assert isinstance(views, list)
    # Single asset → at least single-asset / allocation insights
    ids = {v.id for v in views}
    assert any("single_asset" in i or "large_allocation" in i or "no_diversification" in i for i in ids)
