"""Formula unit tests."""

from app.analytics.formulas import (
    allocation_pct,
    expectancy,
    max_drawdown_from_series,
    profit_factor,
    recovery_factor,
    roi,
    win_rate,
)


def test_roi() -> None:
    assert roi(50, 200) == 25.0
    assert roi(10, 0) == 0.0


def test_profit_factor() -> None:
    assert profit_factor(300, -100) == 3.0
    assert profit_factor(100, 0) == float("inf")


def test_win_rate() -> None:
    assert win_rate(3, 4) == 75.0


def test_expectancy() -> None:
    exp = expectancy(100.0, -50.0, 50.0)
    assert exp == 25.0


def test_recovery_factor() -> None:
    assert recovery_factor(500, 250) == 2.0


def test_allocation_pct() -> None:
    assert allocation_pct(25, 100) == 25.0


def test_max_drawdown() -> None:
    assert max_drawdown_from_series([100, 120, 90, 110]) == 30.0
