from app.insights.rules.assets import GoalProgressRule, GoalTrackingStubRule
from tests.test_insights.conftest_helpers import make_bundle, make_capital, make_trades


def test_goal_hint_when_missing() -> None:
    bundle = make_bundle(
        capital=make_capital(cash_invested=100, roi_pct=5),
        trades=make_trades(total_trades=1),
        goal_roi_pct=None,
    )
    # inject via replace - AnalyticsBundle is frozen with default None
    assert len(GoalTrackingStubRule().evaluate(bundle)) == 1


def test_goal_progress_met() -> None:
    from app.analytics.models import AnalyticsBundle
    from tests.test_insights.conftest_helpers import empty_charts, make_trades

    base = make_bundle(
        capital=make_capital(cash_invested=100, roi_pct=20),
        trades=make_trades(total_trades=2),
    )
    bundle = AnalyticsBundle(
        capital=base.capital,
        trades=base.trades,
        assets=base.assets,
        periods=base.periods,
        charts=empty_charts(),
        growth_series=base.growth_series,
        fingerprint="g",
        goal_roi_pct=15.0,
    )
    out = GoalProgressRule().evaluate(bundle)
    assert len(out) == 1
    assert "محقق" in out[0].title or "هدف" in out[0].title
