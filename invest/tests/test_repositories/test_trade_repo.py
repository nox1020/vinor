from app.config import TRADE_STATUS_OPEN
from app.models.trade import Trade
from app.services.trade_service import TradeService


def test_trade_repo_create(trade_service: TradeService) -> None:
    asset = trade_service.create_asset(name="X", symbol="X")
    trade = Trade(
        id=None,
        asset_id=asset.id,
        status=TRADE_STATUS_OPEN,
        quantity=1,
        buy_price=10,
        buy_fee=0,
        buy_date="2024-06-01",
    )
    created = trade_service.trades.create(trade)
    assert created.id is not None
    assert trade_service.trades.get(created.id) is not None
