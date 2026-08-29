from app.services.trade_service import TradeService


def test_register_buy_and_inventory(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(name="BTC", symbol="BTC", quantity=0)
    trade = trade_service.register_buy(
        asset_id=asset.id,
        quantity=2,
        buy_price=100,
    )
    assert trade.is_open
    updated = trade_service.assets.get(asset.id)
    assert updated is not None
    assert updated.quantity == 2
    assert updated.avg_buy_price == 100


def test_partial_close(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(
        name="ETH",
        symbol="ETH",
        quantity=10,
        avg_buy_price=50,
        current_price=50,
    )
    open_trades = trade_service.trades.list_open()
    assert len(open_trades) == 1
    lot = open_trades[0]
    closed = trade_service.close_trade(
        lot.id,
        sell_price=60,
        quantity=4,
    )
    assert closed.is_closed
    assert closed.quantity == 4
    remaining = trade_service.trades.get(lot.id)
    assert remaining is not None
    assert remaining.is_open
    assert remaining.quantity == 6
    remaining_asset = trade_service.assets.get(asset.id)
    assert remaining_asset is not None
    assert remaining_asset.quantity == 6
    # Remaining inventory keeps the previous mark, not the sell price.
    assert remaining_asset.current_price == 50


def test_avg_buy_price_includes_fees(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(name="FEE", symbol="FEE", quantity=0)
    trade_service.register_buy(
        asset_id=asset.id,
        quantity=2,
        buy_price=100,
        buy_fee=20,
    )
    updated = trade_service.assets.get(asset.id)
    assert updated is not None
    assert updated.quantity == 2
    assert updated.avg_buy_price == 110


def test_roi_after_full_close(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(
        name="Y",
        symbol="Y",
        quantity=1,
        avg_buy_price=100,
        current_price=100,
    )
    lot = trade_service.trades.list_open()[0]
    trade_service.close_trade(lot.id, sell_price=150)
    m = trade_service.portfolio.get_metrics()
    assert m.total_pnl == 50
    assert m.total_cost == 0
    assert abs(m.total_pnl_pct - 50.0) < 1e-9


def test_gold_fund_metrics_from_buys_and_sells(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(
        name="طلا",
        symbol="GOLD",
        quantity=0,
        avg_buy_price=0,
        current_price=30_000_000,
    )
    trade_service.register_buy(
        asset_id=asset.id,
        quantity=10,
        buy_price=30_000_000,
    )
    open_lot = trade_service.trades.list_open()[0]
    trade_service.close_trade(open_lot.id, sell_price=31_000_000, quantity=4)

    m = trade_service.gold_fund_metrics()
    assert m.gold_in_g == 10
    assert m.gold_out_g == 4
    assert m.gold_holding_g == 6
    assert m.gold_debt_g == 6
    assert abs(m.gold_in_g - m.gold_out_g - m.gold_holding_g) < 1e-9

    gold_asset = trade_service.assets.get(asset.id)
    assert gold_asset is not None
    assert gold_asset.quantity == 6


def test_gold_fund_ignores_non_gold(trade_service: TradeService) -> None:
    trade_service.create_asset(
        name="بیت‌کوین",
        symbol="BTC",
        quantity=2,
        avg_buy_price=100,
        current_price=110,
    )
    trade_service.create_asset(
        name="سکه طلا",
        symbol="COIN",
        quantity=1,
        avg_buy_price=50_000_000,
        current_price=50_000_000,
    )
    m = trade_service.gold_fund_metrics()
    assert m.gold_in_g == 0
    assert m.gold_out_g == 0
    assert m.gold_holding_g == 0
