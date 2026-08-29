from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from app.services.portfolio_service import PortfolioService


def test_analyze_empty(db_conn) -> None:
    portfolio = PortfolioService(db_conn)
    svc = PortfolioAnalyticsService(portfolio)
    bundle = svc.analyze(calendar="jalali")
    assert bundle.capital.portfolio_value == 0.0
    assert bundle.trades.closed_trades == 0


def test_analyze_after_trade(trade_service) -> None:
    trade_service.create_asset(name="X", symbol="X", quantity=0)
    asset = trade_service.assets.list_all()[0]
    trade_service.register_buy(asset_id=asset.id, quantity=1, buy_price=100)
    asset = trade_service.assets.get(asset.id)
    assert asset is not None
    asset.current_price = 110
    trade_service.assets.update(asset)

    svc = PortfolioAnalyticsService(trade_service.portfolio)
    bundle = svc.analyze(calendar="jalali")
    assert bundle.capital.portfolio_value == 110
    assert bundle.capital.unrealized_pnl == 10
    assert len(bundle.assets) == 1
    assert bundle.assets[0].allocation_pct == 100.0
