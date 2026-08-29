"""Portfolio analytics engine — all calculations, no UI."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.analytics.formulas import (
    allocation_pct,
    expectancy,
    loss_rate,
    max_drawdown_from_series,
    profit_factor,
    recovery_factor,
    roi,
    weighted_average,
    win_rate,
)
from app.analytics.models import (
    AnalyticsBundle,
    AssetAnalyticsRow,
    ChartBundle,
    ChartSeries,
    PeriodPerformance,
    PortfolioCapitalMetrics,
    TradeAnalytics,
)
from app.analytics.periods import PERIOD_TYPES, bucket_key
from app.models.asset import Asset
from app.models.trade import Trade
from app.services.portfolio_service import PortfolioService


@dataclass
class _TradeLists:
    assets: list[Asset]
    open_trades: list[Trade]
    closed_trades: list[Trade]


class PortfolioAnalyticsService:
    """
    Investment analytics over live portfolio data.

    Data access only via ``PortfolioService`` (no direct repository usage).
    """

    def __init__(self, portfolio: PortfolioService) -> None:
        self._portfolio = portfolio
        self._cache: AnalyticsBundle | None = None
        self._cache_fp: str | None = None

    def invalidate_cache(self) -> None:
        self._cache = None
        self._cache_fp = None

    def analyze(
        self,
        *,
        calendar: str,
        growth_series: list[tuple[str, float]] | None = None,
        persist_growth: bool = False,
        goal_roi_pct: float | None = None,
    ) -> AnalyticsBundle:
        fp = self._fingerprint(goal_roi_pct=goal_roi_pct)
        if self._cache is not None and self._cache_fp == fp and growth_series is None:
            return self._cache

        data = self._load_trades()
        series = growth_series
        if series is None:
            series = self._portfolio.growth_series(persist=persist_growth)

        capital = self._capital_metrics(data)
        trade_a = self._trade_analytics(data, series, capital.net_profit)
        assets = self._asset_analytics(data, capital)
        periods = {
            p: self._period_performance(data.closed_trades, p, calendar, series)
            for p in PERIOD_TYPES
        }
        charts = self._chart_bundle(data, capital, assets, series, periods)

        bundle = AnalyticsBundle(
            capital=capital,
            trades=trade_a,
            assets=assets,
            periods=periods,
            charts=charts,
            growth_series=series,
            fingerprint=fp,
            goal_roi_pct=goal_roi_pct,
        )
        if growth_series is None:
            self._cache = bundle
            self._cache_fp = fp
        return bundle

    def _fingerprint(self, *, goal_roi_pct: float | None = None) -> str:
        assets = self._portfolio.assets.list_all()
        closed = self._portfolio.trades.list_closed()
        open_t = self._portfolio.trades.list_open()
        payload = (
            f"{len(assets)}:{len(closed)}:{len(open_t)}:"
            f"{''.join(a.updated_at for a in assets)}:"
            f"{''.join(t.updated_at for t in closed + open_t)}:"
            f"goal={goal_roi_pct}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _load_trades(self) -> _TradeLists:
        return _TradeLists(
            assets=self._portfolio.assets.list_all(),
            open_trades=self._portfolio.trades.list_open(),
            closed_trades=self._portfolio.trades.list_closed(),
        )

    def _capital_metrics(self, data: _TradeLists) -> PortfolioCapitalMetrics:
        assets = data.assets
        portfolio_value = sum(a.total_value for a in assets)
        total_asset_value = portfolio_value
        cash_invested = sum(a.cost_basis for a in assets)

        open_cost = sum(t.buy_cost for t in data.open_trades)
        current_exposure = sum(t.quantity * t.current_price for t in data.open_trades)

        unrealized = sum(a.unrealized_pnl for a in assets)
        closed_stats = self._portfolio.trades.closed_stats()
        realized = float(closed_stats["total_pnl"])

        total_pnl = realized + unrealized
        lifetime = sum(t.buy_cost for t in data.open_trades + data.closed_trades)
        invested_for_roi = lifetime if lifetime > 0 else cash_invested
        total_pnl_pct = roi(total_pnl, invested_for_roi)
        roi_pct = total_pnl_pct

        all_trades = data.open_trades + data.closed_trades
        total_fees = sum(t.buy_fee + (t.sell_fee if t.is_closed else 0) for t in all_trades)
        net_profit = total_pnl

        winners = [t.realized_pnl for t in data.closed_trades if (t.realized_pnl or 0) > 0]
        losers = [t.realized_pnl for t in data.closed_trades if (t.realized_pnl or 0) < 0]
        gross_profit = sum(winners) if winners else 0.0
        gross_loss = sum(losers) if losers else 0.0

        buy_prices: list[float] = []
        buy_weights: list[float] = []
        for t in all_trades:
            buy_prices.append(t.buy_price)
            buy_weights.append(t.quantity)
        average_buy_price = weighted_average(buy_prices, buy_weights)

        sell_prices = [float(t.sell_price) for t in data.closed_trades if t.sell_price]
        sell_weights = [t.quantity for t in data.closed_trades if t.sell_price]
        average_sell_price = weighted_average(sell_prices, sell_weights)

        trade_sizes = [t.buy_cost for t in all_trades]
        average_trade_size = sum(trade_sizes) / len(trade_sizes) if trade_sizes else 0.0

        holding_days = [t.holding_days for t in data.closed_trades if t.holding_days is not None]
        average_holding_days = (
            sum(holding_days) / len(holding_days) if holding_days else 0.0
        )

        return PortfolioCapitalMetrics(
            portfolio_value=portfolio_value,
            total_asset_value=total_asset_value,
            cash_invested=cash_invested,
            current_exposure=current_exposure,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            roi_pct=roi_pct,
            total_fees=total_fees,
            net_profit=net_profit,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            average_buy_price=average_buy_price,
            average_sell_price=average_sell_price,
            average_trade_size=average_trade_size,
            average_holding_days=average_holding_days,
        )

    def _trade_analytics(
        self,
        data: _TradeLists,
        growth_series: list[tuple[str, float]],
        net_profit: float,
    ) -> TradeAnalytics:
        closed = data.closed_trades
        pnls = [float(t.realized_pnl or 0) for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_count = len(wins)
        loss_count = len(losses)
        closed_count = len(closed)

        avg_profit = sum(wins) / win_count if win_count else 0.0
        avg_loss = sum(losses) / loss_count if loss_count else 0.0
        max_profit = max(pnls) if pnls else 0.0
        max_loss = min(pnls) if pnls else 0.0

        wr = win_rate(win_count, closed_count)
        lr = loss_rate(loss_count, closed_count)
        gp = sum(wins) if wins else 0.0
        gl = sum(losses) if losses else 0.0
        pf = profit_factor(gp, gl)
        exp = expectancy(avg_profit, avg_loss, wr)

        values = [v for _, v in growth_series]
        mdd = max_drawdown_from_series(values)
        rf = recovery_factor(net_profit, mdd)

        return TradeAnalytics(
            total_trades=len(data.open_trades) + closed_count,
            open_trades=len(data.open_trades),
            closed_trades=closed_count,
            average_profit=avg_profit,
            average_loss=avg_loss,
            max_profit=max_profit,
            max_loss=max_loss,
            win_rate_pct=wr,
            loss_rate_pct=lr,
            profit_factor=pf if pf != float("inf") else 0.0,
            average_winner=avg_profit,
            average_loser=avg_loss,
            largest_winner=max_profit,
            largest_loser=max_loss,
            expectancy=exp,
            recovery_factor=rf if rf != float("inf") else 0.0,
        )

    def _asset_analytics(
        self,
        data: _TradeLists,
        capital: PortfolioCapitalMetrics,
    ) -> list[AssetAnalyticsRow]:
        total_val = capital.portfolio_value
        total_realized = capital.realized_pnl
        rows: list[AssetAnalyticsRow] = []

        for asset in data.assets:
            if asset.id is None:
                continue
            asset_trades = [
                t
                for t in data.open_trades + data.closed_trades
                if t.asset_id == asset.id
            ]
            realized = sum(float(t.realized_pnl or 0) for t in asset_trades if t.is_closed)
            ret_amt = realized + asset.unrealized_pnl
            lifetime = sum(t.buy_cost for t in asset_trades)
            invested = lifetime if lifetime > 0 else asset.cost_basis
            ret_pct = roi(ret_amt, invested)
            profit_share = (
                (realized / total_realized * 100.0) if total_realized else 0.0
            )

            dates: list[str] = []
            for t in asset_trades:
                dates.append(t.buy_date[:10])
                if t.sell_date:
                    dates.append(t.sell_date[:10])
            dates.sort()
            holding = [
                t.holding_days for t in asset_trades if t.is_closed and t.holding_days
            ]
            avg_hold = sum(holding) / len(holding) if holding else 0.0

            rows.append(
                AssetAnalyticsRow(
                    asset_id=asset.id,
                    name=asset.name,
                    symbol=asset.symbol,
                    allocation_pct=allocation_pct(asset.total_value, total_val),
                    profit_share_pct=profit_share,
                    return_amount=ret_amt,
                    return_pct=ret_pct,
                    invested=invested,
                    current_value=asset.total_value,
                    realized_pnl=realized,
                    unrealized_pnl=asset.unrealized_pnl,
                    trade_count=len(asset_trades),
                    first_trade_date=dates[0] if dates else None,
                    last_trade_date=dates[-1] if dates else None,
                    average_holding_days=avg_hold,
                )
            )
        rows.sort(key=lambda r: r.current_value, reverse=True)
        return rows

    def _period_performance(
        self,
        closed: list[Trade],
        period: str,
        calendar: str,
        growth_series: list[tuple[str, float]],
    ) -> list[PeriodPerformance]:
        buckets: dict[str, list[Trade]] = {}
        for t in closed:
            if not t.sell_date:
                continue
            key = bucket_key(t.sell_date[:10], period, calendar)
            buckets.setdefault(key, []).append(t)

        growth_by_key: dict[str, float] = dict(growth_series)
        result: list[PeriodPerformance] = []
        for key in sorted(buckets.keys()):
            trades = buckets[key]
            pnls = [float(t.realized_pnl or 0) for t in trades]
            profit = sum(p for p in pnls if p > 0)
            loss = sum(p for p in pnls if p < 0)
            net = sum(pnls)
            wins = sum(1 for p in pnls if p > 0)
            sr = win_rate(wins, len(trades))
            cap = growth_by_key.get(key, 0.0)
            growth_pct = 0.0
            result.append(
                PeriodPerformance(
                    key=key,
                    profit=profit,
                    loss=loss,
                    net_pnl=net,
                    trade_count=len(trades),
                    win_count=wins,
                    success_rate_pct=sr,
                    capital_growth_pct=growth_pct,
                )
            )
        if period == "all" and closed:
            pnls = [float(t.realized_pnl or 0) for t in closed]
            profit = sum(p for p in pnls if p > 0)
            loss = sum(p for p in pnls if p < 0)
            wins = sum(1 for p in pnls if p > 0)
            result = [
                PeriodPerformance(
                    key="all",
                    profit=profit,
                    loss=loss,
                    net_pnl=sum(pnls),
                    trade_count=len(closed),
                    win_count=wins,
                    success_rate_pct=win_rate(wins, len(closed)),
                    capital_growth_pct=0.0,
                )
            ]
        return result

    def _chart_bundle(
        self,
        data: _TradeLists,
        capital: PortfolioCapitalMetrics,
        asset_rows: list[AssetAnalyticsRow],
        growth_series: list[tuple[str, float]],
        periods: dict[str, list[PeriodPerformance]],
    ) -> ChartBundle:
        cap = ChartSeries("capital_trend", list(growth_series))
        profit_trend = ChartSeries(
            "profit_trend",
            [(p.key, p.net_pnl) for p in periods.get("daily", [])],
        )
        alloc = ChartSeries(
            "allocation",
            [(a.name, a.allocation_pct) for a in asset_rows],
        )
        growth = ChartSeries("capital_growth", list(growth_series))
        monthly = ChartSeries(
            "monthly_profit",
            [(p.key, p.net_pnl) for p in periods.get("monthly", [])],
        )
        yearly = ChartSeries(
            "yearly_profit",
            [(p.key, p.net_pnl) for p in periods.get("yearly", [])],
        )
        by_asset = ChartSeries(
            "by_asset_value",
            [(a.name, a.total_value) for a in data.assets],
        )
        comparison = ChartSeries(
            "asset_comparison",
            [(a.name, a.return_pct) for a in asset_rows],
        )
        return ChartBundle(
            capital_trend=cap,
            profit_trend=profit_trend,
            allocation=alloc,
            capital_growth=growth,
            monthly_profit=monthly,
            yearly_profit=yearly,
            by_asset_value=by_asset,
            asset_comparison=comparison,
        )
