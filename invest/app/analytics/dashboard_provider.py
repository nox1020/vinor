"""Dashboard-facing data (no UI imports)."""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from app.services.portfolio_service import DashboardMetrics, PortfolioService
from app.services.trade_service import GoldFundMetrics, TradeService
from app.utils.dates import period_key, today_iso


@dataclass(frozen=True)
class DashboardData:
    """Everything the dashboard page needs to render (display-only strings optional)."""

    metrics: DashboardMetrics
    growth_series: list[tuple[str, float]]
    asset_summary: list[tuple[str, float, float]]  # name, qty, value
    gold_fund: GoldFundMetrics


class DashboardDataProvider:
    """Build dashboard payloads from analytics + portfolio growth (no UI math)."""

    def __init__(
        self,
        portfolio: PortfolioService,
        analytics: PortfolioAnalyticsService,
        trades: TradeService,
    ) -> None:
        self._portfolio = portfolio
        self._analytics = analytics
        self._trades = trades

    def build(
        self,
        *,
        calendar: str,
        persist_growth: bool = True,
        growth_series: list[tuple[str, float]] | None = None,
    ) -> DashboardData:
        series = growth_series
        if series is None:
            series = self._portfolio.growth_series(persist=persist_growth)

        bundle = self._analytics.analyze(
            calendar=calendar,
            growth_series=series,
            persist_growth=False,
        )
        cap = bundle.capital
        tr = bundle.trades

        today_pnl, today_pnl_pct = self._portfolio.cash_flow_adjusted_day_pnl(
            cap.portfolio_value, series
        )
        annual_return = self._portfolio.cash_flow_adjusted_return_pct(
            cap.portfolio_value, series
        )
        if not series and cap.cash_invested:
            annual_return = (
                (cap.portfolio_value - cap.cash_invested) / cap.cash_invested * 100.0
            )

        year_key = period_key(today_iso(), "yearly", calendar)
        year_realized = 0.0
        for p in bundle.periods.get("yearly", []):
            if p.key == year_key:
                year_realized = float(p.net_pnl)
                break

        metrics = DashboardMetrics(
            total_value=cap.portfolio_value,
            total_cost=cap.cash_invested,
            total_pnl=cap.total_pnl,
            total_pnl_pct=cap.total_pnl_pct,
            open_count=tr.open_trades,
            closed_count=tr.closed_trades,
            realized_pnl=cap.realized_pnl,
            unrealized_pnl=cap.unrealized_pnl,
            max_profit=tr.max_profit,
            max_loss=tr.max_loss,
            today_pnl=today_pnl,
            today_pnl_pct=today_pnl_pct,
            annual_return_pct=annual_return,
            year_realized_pnl=year_realized,
            year_key=year_key,
        )

        assets = self._portfolio.assets.list_all()
        summary = [(a.name, a.quantity, a.total_value) for a in assets[:12]]
        gold_fund = self._trades.gold_fund_metrics()

        return DashboardData(
            metrics=metrics,
            growth_series=series,
            asset_summary=summary,
            gold_fund=gold_fund,
        )

    def invalidate(self) -> None:
        self._analytics.invalidate_cache()
