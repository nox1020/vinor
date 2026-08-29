"""Optional sample data seeder for demos and first-time exploration."""

from __future__ import annotations

from datetime import date, timedelta

from app.bootstrap import bootstrap
from app.utils.dates import today_iso


def seed() -> None:
    ctx = bootstrap()
    if ctx.portfolio.assets.list_all():
        print("Sample data already exists; seed skipped.")
        ctx.close()
        return

    # Sample assets + buys
    today = date.today()
    ctx.trades.register_buy(
        name="تتر",
        symbol="USDT",
        quantity=189,
        buy_price=92000,
        buy_fee=0,
        buy_date=(today - timedelta(days=40)).isoformat(),
        buy_note="موجودی نقد",
        current_price=92000,
    )
    ctx.trades.register_buy(
        name="شیبا",
        symbol="SHIB",
        quantity=50_000_000,
        buy_price=0.42,
        buy_fee=15000,
        buy_date=(today - timedelta(days=25)).isoformat(),
        current_price=0.48,
    )
    ctx.trades.register_buy(
        name="طلا",
        symbol="GOLD",
        quantity=2.5,
        buy_price=28_500_000,
        buy_fee=50000,
        buy_date=(today - timedelta(days=18)).isoformat(),
        current_price=29_200_000,
    )
    open_trades = ctx.trades.trades.list_open()
    # Close one older-style profit demo if we have enough trades
    if len(open_trades) >= 1:
        # Create and close a separate demo trade for realized PnL
        demo = ctx.trades.register_buy(
            name="بیت‌کوین",
            symbol="BTC",
            quantity=0.01,
            buy_price=4_000_000_000,
            buy_fee=100000,
            buy_date=(today - timedelta(days=60)).isoformat(),
            current_price=4_200_000_000,
        )
        ctx.trades.close_trade(
            demo.id,
            sell_price=4_350_000_000,
            sell_fee=120000,
            sell_date=(today - timedelta(days=10)).isoformat(),
            sell_note="نمونه معامله بسته",
        )

    ctx.portfolio.record_snapshot()
    # Backfill a couple of historical snapshots for the chart
    from app.repositories.snapshot_repo import SnapshotRepository

    snaps = SnapshotRepository(ctx.conn)
    value = ctx.portfolio.total_portfolio_value()
    snaps.upsert_today(value * 0.92, (today - timedelta(days=30)).isoformat())
    snaps.upsert_today(value * 0.96, (today - timedelta(days=15)).isoformat())
    snaps.upsert_today(value, today_iso())

    print("Sample data inserted successfully.")
    ctx.close()


if __name__ == "__main__":
    seed()
