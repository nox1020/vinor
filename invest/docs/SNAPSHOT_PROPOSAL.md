# Snapshot redesign — APPLIED (migration v2)

## Goal

Store **true daily portfolio state** for analytics and drawdown, not only total mark-to-market.

## Tables

### `portfolio_snapshots`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| snapshot_date | TEXT UNIQUE | ISO date |
| total_value | REAL | Portfolio MTM |
| cash_invested | REAL | Cost basis |
| realized_pnl_cumulative | REAL | Sum closed PnL to date |
| unrealized_pnl | REAL | MTM − cost |
| total_fees_cumulative | REAL | Sum of fees |
| created_at | TEXT | Capture timestamp |

### `portfolio_snapshot_assets`

Per-asset rows for each snapshot (quantity, price, value, weight_pct).

## Strategy (implemented)

1. Tables added without dropping `capital_snapshots`.
2. Backfill totals from existing `capital_snapshots`.
3. Dual-write from `PortfolioService.record_snapshot`.
4. Registered as migration version **2** in `schema_migrations`.

## Cash

Still no separate cash ledger. Cash invested = asset cost basis.
