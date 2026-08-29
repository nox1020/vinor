"""Unit tests for individual insight rules."""

from app.insights.rules.assets import BestAssetRule, WorstAssetRule
from app.insights.rules.behavior import InactivePortfolioRule, OverTradingRule
from app.insights.rules.performance import LowWinRateRule, NegativeRoiRule
from app.insights.rules.risk import LargeAllocationRule, SingleAssetRiskRule
from tests.test_insights.conftest_helpers import (
    make_asset,
    make_bundle,
    make_capital,
    make_trades,
)


def test_large_allocation_triggers() -> None:
    bundle = make_bundle(
        assets=[make_asset(name="Gold", allocation_pct=55, current_value=55)]
    )
    out = LargeAllocationRule().evaluate(bundle)
    assert len(out) == 1
    assert out[0].rule_id == "large_allocation"


def test_large_allocation_skips_below_threshold() -> None:
    bundle = make_bundle(
        assets=[make_asset(name="Gold", allocation_pct=20, current_value=20)]
    )
    assert LargeAllocationRule().evaluate(bundle) == []


def test_single_asset_risk() -> None:
    bundle = make_bundle(
        assets=[make_asset(name="Only", allocation_pct=100, current_value=100)]
    )
    out = SingleAssetRiskRule().evaluate(bundle)
    assert len(out) == 1


def test_single_asset_risk_skips_multiple() -> None:
    bundle = make_bundle(
        assets=[
            make_asset(asset_id=1, name="A", current_value=50),
            make_asset(asset_id=2, name="B", current_value=50),
        ]
    )
    assert SingleAssetRiskRule().evaluate(bundle) == []


def test_negative_roi() -> None:
    bundle = make_bundle(capital=make_capital(roi_pct=-15, cash_invested=1000))
    out = NegativeRoiRule().evaluate(bundle)
    assert len(out) == 1


def test_negative_roi_skips_positive() -> None:
    bundle = make_bundle(capital=make_capital(roi_pct=5, cash_invested=1000))
    assert NegativeRoiRule().evaluate(bundle) == []


def test_low_win_rate() -> None:
    bundle = make_bundle(
        trades=make_trades(closed_trades=10, win_rate_pct=30),
    )
    assert len(LowWinRateRule().evaluate(bundle)) == 1


def test_low_win_rate_needs_sample() -> None:
    bundle = make_bundle(trades=make_trades(closed_trades=2, win_rate_pct=10))
    assert LowWinRateRule().evaluate(bundle) == []


def test_over_trading() -> None:
    bundle = make_bundle(
        trades=make_trades(closed_trades=12),
        capital=make_capital(average_holding_days=3),
    )
    assert len(OverTradingRule().evaluate(bundle)) == 1


def test_inactive_portfolio() -> None:
    bundle = make_bundle()
    assert len(InactivePortfolioRule().evaluate(bundle)) == 1


def test_best_and_worst_asset() -> None:
    bundle = make_bundle(
        assets=[
            make_asset(asset_id=1, name="Win", return_amount=100, return_pct=10),
            make_asset(asset_id=2, name="Lose", return_amount=-50, return_pct=-5),
        ]
    )
    assert BestAssetRule().evaluate(bundle)[0].related_assets == ("Win",)
    assert WorstAssetRule().evaluate(bundle)[0].related_assets == ("Lose",)
