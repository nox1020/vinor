from datetime import date, timedelta

from app.services.trade_service import TradeService
from app.utils.dates import today_iso


def test_record_snapshot(trade_service: TradeService, db_conn) -> None:
    trade_service.create_asset(
        name="Gold",
        symbol="GOLD",
        quantity=1,
        avg_buy_price=1_000_000,
        current_price=1_100_000,
    )
    portfolio = trade_service.portfolio
    value = portfolio.record_snapshot()
    assert value > 0


def test_get_metrics_after_buy(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(name="USDT", symbol="USDT", quantity=0)
    trade_service.register_buy(asset_id=asset.id, quantity=100, buy_price=65_000)
    m = trade_service.portfolio.get_metrics()
    assert m.open_count >= 1
    assert m.total_value > 0
    assert hasattr(m, "year_realized_pnl")
    assert m.year_key


def test_today_pnl_excludes_same_day_buy(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(
        name="X",
        symbol="X",
        quantity=1,
        avg_buy_price=100,
        current_price=100,
    )
    trade_service.register_buy(asset_id=asset.id, quantity=1, buy_price=100)
    today = today_iso()
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    value = trade_service.portfolio.total_portfolio_value()
    series = [(yesterday, 0.0), (today, value)]
    pnl, _pct = trade_service.portfolio.cash_flow_adjusted_day_pnl(value, series)
    assert abs(pnl) < 1e-6
