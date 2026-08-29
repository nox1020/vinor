"""Portfolio aggregation and dashboard metrics."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import CALENDAR_JALALI, TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN
from app.repositories.asset_repo import AssetRepository
from app.repositories.portfolio_snapshot_repo import (
    PortfolioSnapshotAsset,
    PortfolioSnapshotRepository,
)
from app.repositories.snapshot_repo import SnapshotRepository
from app.repositories.trade_repo import TradeRepository
from app.utils import calc
from app.utils.dates import iter_dates, parse_iso_date, period_key, today_iso


@dataclass
class DashboardMetrics:
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float
    open_count: int
    closed_count: int
    realized_pnl: float
    unrealized_pnl: float
    max_profit: float
    max_loss: float
    today_pnl: float
    today_pnl_pct: float
    annual_return_pct: float
    year_realized_pnl: float = 0.0
    year_key: str = ""


class PortfolioService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.assets = AssetRepository(conn)
        self.trades = TradeRepository(conn)
        self.snapshots = SnapshotRepository(conn)
        self.portfolio_snapshots = PortfolioSnapshotRepository(conn)

    def total_portfolio_value(self) -> float:
        return sum(a.total_value for a in self.assets.list_all())

    def total_cost_basis(self) -> float:
        return sum(a.cost_basis for a in self.assets.list_all())

    def record_snapshot(self) -> float:
        """Persist today's live portfolio value (legacy + rich snapshot)."""
        today = today_iso()
        assets = self.assets.list_all()
        value = sum(a.total_value for a in assets)
        cost = sum(a.cost_basis for a in assets)
        unrealized = value - cost
        stats = self.trades.closed_stats()
        realized = float(stats["total_pnl"])
        fees = 0.0
        for t in self.trades.list_open() + self.trades.list_closed():
            fees += float(t.buy_fee) + (float(t.sell_fee) if t.is_closed else 0.0)

        # Legacy chart table (unchanged consumers).
        self.snapshots.upsert(value, today)

        snap_assets: list[PortfolioSnapshotAsset] = []
        for a in assets:
            if a.id is None:
                continue
            weight = (a.total_value / value * 100.0) if value else 0.0
            snap_assets.append(
                PortfolioSnapshotAsset(
                    asset_id=a.id,
                    quantity=a.quantity,
                    price=a.current_price,
                    value=a.total_value,
                    weight_pct=weight,
                )
            )
        try:
            self.portfolio_snapshots.upsert(
                total_value=value,
                cash_invested=cost,
                realized_pnl_cumulative=realized,
                unrealized_pnl=unrealized,
                total_fees_cumulative=fees,
                assets=snap_assets,
                date_str=today,
            )
        except sqlite3.Error:
            # Table may be missing until migrations run; legacy still written.
            pass
        return value

    def ensure_daily_history(self) -> list[tuple[str, float]]:
        """Build/backfill the daily series without rewriting trusted past days."""
        return self.growth_series(persist=True)

    def net_external_cash(self, day: str) -> float:
        """Net capital added on ``day``: buy costs minus sell proceeds."""
        day = (day or "")[:10]
        if not day:
            return 0.0
        added = 0.0
        for trade in self.trades.list_open() + self.trades.list_closed():
            if (trade.buy_date or "")[:10] == day:
                added += float(trade.quantity) * float(trade.buy_price) + float(
                    trade.buy_fee or 0
                )
            if trade.is_closed and (trade.sell_date or "")[:10] == day:
                proceeds = float(trade.quantity) * float(trade.sell_price or 0) - float(
                    trade.sell_fee or 0
                )
                added -= proceeds
        return added

    def net_external_cash_after(self, after_day: str, through: str | None = None) -> float:
        """Net capital added after ``after_day`` through ``through`` (inclusive)."""
        start = (after_day or "")[:10]
        end = (through or today_iso())[:10]
        if not start:
            return 0.0
        added = 0.0
        for trade in self.trades.list_open() + self.trades.list_closed():
            buy_d = (trade.buy_date or "")[:10]
            if start < buy_d <= end:
                added += float(trade.quantity) * float(trade.buy_price) + float(
                    trade.buy_fee or 0
                )
            if trade.is_closed:
                sell_d = (trade.sell_date or "")[:10]
                if start < sell_d <= end:
                    proceeds = float(trade.quantity) * float(
                        trade.sell_price or 0
                    ) - float(trade.sell_fee or 0)
                    added -= proceeds
        return added

    def cash_flow_adjusted_day_pnl(
        self,
        current_value: float,
        series: list[tuple[str, float]],
        *,
        day: str | None = None,
    ) -> tuple[float, float]:
        """Today's PnL excluding deposits/withdrawals (buy/sell cash)."""
        if len(series) < 2:
            return 0.0, 0.0
        prev_value = series[-2][1]
        day = (day or today_iso())[:10]
        pnl = current_value - prev_value - self.net_external_cash(day)
        pct = (pnl / prev_value * 100.0) if prev_value else 0.0
        return pnl, pct

    def cash_flow_adjusted_return_pct(
        self,
        current_value: float,
        series: list[tuple[str, float]],
    ) -> float:
        """Growth % after stripping later deposits/withdrawals from the value delta."""
        if not series:
            return 0.0
        first_day, first_val = series[0]
        if first_val <= 0:
            return 0.0
        later = self.net_external_cash_after(first_day)
        return ((current_value - first_val - later) / first_val) * 100.0

    def lifetime_invested(self) -> float:
        """Sum of buy costs (qty * price + fee) across open and closed lots."""
        total = 0.0
        for trade in self.trades.list_open() + self.trades.list_closed():
            total += float(trade.quantity) * float(trade.buy_price) + float(
                trade.buy_fee or 0
            )
        return total

    def get_metrics(
        self,
        *,
        growth_series: list[tuple[str, float]] | None = None,
        calendar: str = CALENDAR_JALALI,
    ) -> DashboardMetrics:
        assets = self.assets.list_all()
        total_value = sum(a.total_value for a in assets)
        total_cost = sum(a.cost_basis for a in assets)
        unrealized = total_value - total_cost
        stats = self.trades.closed_stats()
        realized = stats["total_pnl"]
        total_pnl = unrealized + realized
        invested = self.lifetime_invested() or total_cost
        total_pnl_pct = (total_pnl / invested * 100.0) if invested else 0.0

        series = (
            growth_series
            if growth_series is not None
            else self.growth_series(persist=False)
        )
        today_pnl, today_pnl_pct = self.cash_flow_adjusted_day_pnl(
            total_value, series
        )
        annual_return = self.cash_flow_adjusted_return_pct(total_value, series)
        if not series and total_cost:
            annual_return = calc.portfolio_return_pct(total_value, total_cost)

        year_key = period_key(today_iso(), "yearly", calendar)
        year_realized = 0.0
        for trade in self.trades.list_closed():
            if not trade.sell_date or trade.realized_pnl is None:
                continue
            if period_key(trade.sell_date[:10], "yearly", calendar) == year_key:
                year_realized += float(trade.realized_pnl)

        return DashboardMetrics(
            total_value=total_value,
            total_cost=total_cost,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            open_count=self.trades.count_by_status(TRADE_STATUS_OPEN),
            closed_count=self.trades.count_by_status(TRADE_STATUS_CLOSED),
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            max_profit=stats["max_profit"],
            max_loss=stats["max_loss"],
            today_pnl=today_pnl,
            today_pnl_pct=today_pnl_pct,
            annual_return_pct=annual_return,
            year_realized_pnl=year_realized,
            year_key=year_key,
        )

    def growth_series(self, *, persist: bool = True) -> list[tuple[str, float]]:
        """
        Daily capital trend from first activity through today.

        - Event days come from the trade timeline (buy/sell), expanded daily.
        - Today always uses the live portfolio value.
        - Snapshots captured on the same calendar day they represent are trusted
          (true daily mark). Backfilled/rewritten rows are ignored for display.
        """
        today = today_iso()
        today_val = self.total_portfolio_value()
        trusted = self._trusted_snapshots()
        reconstructed = self._daily_series_from_trades(through=today)

        start_candidates: list[str] = []
        if trusted:
            start_candidates.append(min(trusted))
        if reconstructed:
            start_candidates.append(min(reconstructed))
        if not start_candidates:
            if today_val:
                series = [(today, today_val)]
                if persist:
                    self.snapshots.upsert(today_val, today)
                return series
            return []

        start = min(start_candidates)
        series: list[tuple[str, float]] = []
        last_val = 0.0

        for d in iter_dates(start, today):
            key = d.isoformat()
            if key == today:
                val = today_val
            elif key in trusted:
                val = trusted[key]
            elif key in reconstructed:
                val = reconstructed[key]
            else:
                val = last_val
            series.append((key, val))
            last_val = val

        if persist:
            self.snapshots.upsert(today_val, today)
            for date_str, value in series:
                if date_str == today:
                    continue
                if date_str not in trusted:
                    self.snapshots.insert_if_missing(value, date_str)

        return series

    def _trusted_snapshots(self) -> dict[str, float]:
        """Snapshots recorded on the same day they represent (real daily marks)."""
        trusted: dict[str, float] = {}
        for snap in self.snapshots.list_all():
            day = (snap.date or "")[:10]
            if not day:
                continue
            created_day = (snap.created_at or "")[:10]
            # Same-day capture, or legacy rows without created_at.
            if not created_day or created_day == day:
                trusted[day] = float(snap.total_value)
        return trusted

    def _event_value_by_date(self) -> dict[str, float]:
        """Portfolio value at end of each buy/sell date (current mark-to-market)."""
        assets = {a.id: a for a in self.assets.list_all() if a.id is not None}
        open_trades = self.trades.list_open()
        closed_trades = self.trades.list_closed()
        all_trades = open_trades + closed_trades
        if not all_trades:
            return {}

        events: list[tuple[str, int, str, object]] = []
        for trade in all_trades:
            buy_d = (trade.buy_date or "")[:10]
            if buy_d:
                events.append((buy_d, 0, "buy", trade))
            if trade.is_closed and trade.sell_date:
                sell_d = trade.sell_date[:10]
                events.append((sell_d, 1, "sell", trade))

        events.sort(key=lambda e: (e[0], e[1], e[3].id or 0))

        open_lots: dict[int, object] = {}
        points: dict[str, float] = {}

        for date_str, _order, kind, trade in events:
            tid = trade.id
            if tid is None:
                continue
            if kind == "buy":
                open_lots[tid] = trade
            else:
                open_lots.pop(tid, None)

            value = 0.0
            for lot in open_lots.values():
                asset = assets.get(lot.asset_id)
                price = asset.current_price if asset else lot.buy_price
                value += float(lot.quantity) * float(price)
            points[date_str] = value

        return points

    def _daily_series_from_trades(self, *, through: str | None = None) -> dict[str, float]:
        """Expand trade event points into a continuous daily series."""
        points = self._event_value_by_date()
        if not points:
            return {}

        end = parse_iso_date(through or today_iso())
        start = parse_iso_date(min(points))
        if end < start:
            end = start

        daily: dict[str, float] = {}
        last = 0.0
        for d in iter_dates(start, end):
            key = d.isoformat()
            if key in points:
                last = points[key]
            daily[key] = last
        return daily
