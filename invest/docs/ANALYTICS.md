# Investment Analytics — Formulas & Metrics

Base currency: **Toman** (stored in SQLite). Display conversion uses existing `format_money`.

## Portfolio capital (`PortfolioCapitalMetrics`)

| Metric | Definition | Formula | Inputs | Limitation |
|--------|------------|---------|--------|------------|
| Portfolio Value | Mark-to-market total | Σ (qty × current_price) | `assets` | Depends on manual/live prices |
| Cash Invested | Cost basis of holdings | Σ (qty × avg_buy_price) | `assets` | avg from open lots sync |
| Current Exposure | Open positions MTM | Σ open qty × current_price | open trades | |
| Realized PnL | Closed trades | Σ `realized_pnl` | closed trades | Fees included in trade PnL |
| Unrealized PnL | Open holdings | Σ (value − cost) | assets | |
| Total PnL | Realized + unrealized | sum above | | |
| ROI % | Return on invested | total_pnl / cash_invested × 100 | `formulas.roi` | 0 if invested=0 |
| Total Fees | Buy + sell fees | Σ fees | all trades | |
| Net Profit | Same as total PnL | | | No separate tax adjustment |
| Gross Profit | Sum of winning closes | Σ pnl where pnl>0 | closed | |
| Gross Loss | Sum of losing closes | Σ pnl where pnl<0 | closed | Negative value |
| Avg Buy Price | Quantity-weighted | weighted avg buy_price | all lots | |
| Avg Sell Price | Quantity-weighted | weighted avg sell_price | closed | |

## Trade analytics (`TradeAnalytics`)

| Metric | Formula | Module |
|--------|---------|--------|
| Win Rate % | wins / closed × 100 | `formulas.win_rate` |
| Loss Rate % | losses / closed × 100 | `formulas.loss_rate` |
| Profit Factor | gross_profit / \|gross_loss\| | `formulas.profit_factor` |
| Expectancy | avg_win×WR + avg_loss×LR | `formulas.expectancy` |
| Recovery Factor | net_profit / max_drawdown | `formulas.recovery_factor` |
| Max Drawdown | Peak-to-trough on growth series | `formulas.max_drawdown_from_series` |

## Asset analytics (`AssetAnalyticsRow`)

| Metric | Formula |
|--------|---------|
| Allocation % | asset_value / portfolio × 100 |
| Profit Share % | asset_realized / total_realized × 100 |
| Return % | portfolio_return_pct(value, cost) |

## Time periods

Buckets: `daily`, `weekly`, `monthly`, `quarterly`, `semi_annual`, `yearly`, `all` — see `app/analytics/periods.py`.

Per bucket: profit (sum wins), loss (sum losses), net PnL, trade count, success rate.

## Architecture

- **Engine:** `PortfolioAnalyticsService` — uses only `PortfolioService`
- **Dashboard:** `DashboardDataProvider` — no UI imports
- **Reports:** `AnalyticsReportGenerator`
- **Charts:** `ChartBundle` inside `AnalyticsBundle` (data only)
- **Export:** `app/analytics/export.py`

## Snapshot (current vs proposed)

**Current DB (`capital_snapshots`):** `date`, `total_value`, `created_at` only.

**Proposed (requires your approval before migration):** see `docs/SNAPSHOT_PROPOSAL.md`.
