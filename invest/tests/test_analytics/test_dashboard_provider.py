from app.analytics.dashboard_provider import DashboardDataProvider
from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from app.services.portfolio_service import PortfolioService


def test_dashboard_provider(trade_service) -> None:
    trade_service.create_asset(
        name="G",
        symbol="GOLD",
        quantity=1,
        avg_buy_price=1000,
        current_price=1000,
    )
    portfolio = trade_service.portfolio
    provider = DashboardDataProvider(
        portfolio, PortfolioAnalyticsService(portfolio), trade_service
    )
    data = provider.build(calendar="jalali", persist_growth=False)
    assert data.metrics.total_value > 0
    assert data.growth_series
    assert data.gold_fund.gold_in_g >= 0
    assert data.gold_fund.gold_holding_g >= 0
    assert data.gold_fund.gold_debt_g >= 0
