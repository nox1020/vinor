"""Helpers to build AnalyticsBundle fixtures for insight tests."""

from __future__ import annotations

from app.analytics.models import (
    AnalyticsBundle,
    AssetAnalyticsRow,
    ChartBundle,
    ChartSeries,
    PeriodPerformance,
    PortfolioCapitalMetrics,
    TradeAnalytics,
)


def empty_charts() -> ChartBundle:
    empty = ChartSeries("x", [])
    return ChartBundle(
        capital_trend=empty,
        profit_trend=empty,
        allocation=empty,
        capital_growth=empty,
        monthly_profit=empty,
        yearly_profit=empty,
        by_asset_value=empty,
        asset_comparison=empty,
    )


def make_capital(**kwargs) -> PortfolioCapitalMetrics:
    base = dict(
        portfolio_value=0.0,
        total_asset_value=0.0,
        cash_invested=0.0,
        current_exposure=0.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        total_pnl=0.0,
        total_pnl_pct=0.0,
        roi_pct=0.0,
        total_fees=0.0,
        net_profit=0.0,
        gross_profit=0.0,
        gross_loss=0.0,
        average_buy_price=0.0,
        average_sell_price=0.0,
        average_trade_size=0.0,
        average_holding_days=0.0,
    )
    base.update(kwargs)
    return PortfolioCapitalMetrics(**base)


def make_trades(**kwargs) -> TradeAnalytics:
    base = dict(
        total_trades=0,
        open_trades=0,
        closed_trades=0,
        average_profit=0.0,
        average_loss=0.0,
        max_profit=0.0,
        max_loss=0.0,
        win_rate_pct=0.0,
        loss_rate_pct=0.0,
        profit_factor=0.0,
        average_winner=0.0,
        average_loser=0.0,
        largest_winner=0.0,
        largest_loser=0.0,
        expectancy=0.0,
        recovery_factor=0.0,
    )
    base.update(kwargs)
    return TradeAnalytics(**base)


def make_asset(**kwargs) -> AssetAnalyticsRow:
    base = dict(
        asset_id=1,
        name="A",
        symbol="A",
        allocation_pct=0.0,
        profit_share_pct=0.0,
        return_amount=0.0,
        return_pct=0.0,
        invested=0.0,
        current_value=0.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        trade_count=0,
        first_trade_date=None,
        last_trade_date=None,
        average_holding_days=0.0,
    )
    base.update(kwargs)
    return AssetAnalyticsRow(**base)


def make_bundle(
    *,
    capital: PortfolioCapitalMetrics | None = None,
    trades: TradeAnalytics | None = None,
    assets: list[AssetAnalyticsRow] | None = None,
    periods: dict | None = None,
    growth_series: list[tuple[str, float]] | None = None,
    fingerprint: str = "test",
    goal_roi_pct: float | None = None,
) -> AnalyticsBundle:
    return AnalyticsBundle(
        capital=capital or make_capital(),
        trades=trades or make_trades(),
        assets=assets or [],
        periods=periods or {},
        charts=empty_charts(),
        growth_series=growth_series or [],
        fingerprint=fingerprint,
        goal_roi_pct=goal_roi_pct,
    )
