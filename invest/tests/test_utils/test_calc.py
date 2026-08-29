from app.utils import calc


def test_realized_pnl_with_fees() -> None:
    pnl = calc.realized_pnl(10, 100, 110, buy_fee=5, sell_fee=3)
    assert pnl == (10 * (110 - 100) - 5 - 3)


def test_return_pct_zero_cost() -> None:
    assert calc.return_pct(0, 100, 110) == 0.0


def test_holding_days() -> None:
    assert calc.holding_days("2024-01-01", "2024-01-11") == 10


def test_portfolio_return_pct() -> None:
    assert calc.portfolio_return_pct(110, 100) == 10.0
