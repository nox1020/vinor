# Architecture — Invest Manager

## Layers

```
main.py → AppContext (bootstrap) → PySide6 UI
                ↓
         Services (domain)
                ↓
         Repositories (SQL)
                ↓
         SQLite (data/invest.db)
```

## Dependency injection

- `app/services/service_factory.py` builds **one** `PortfolioService` shared by `TradeService` and `ReportService`.
- UI receives a single `AppContext` with all services.

## Threading rules

1. **SQLite:** only the Qt main thread uses `AppContext.conn`.
2. **Live prices:** `app/ui/workers/quotes_worker.py` runs HTTP in a `QThread` with **temporary** `FxService` / `MarketService` instances.
3. After fetch, the UI thread calls `apply_fetched_rate` / `apply_fetched_gold`, then `persist_live_quotes()` and `sync_live_prices_to_portfolio()`.

## Logging

- Configured in `app/logging_config.py`, invoked from `main.py`.
- Daily rotation under `data/logs/invest.log`.

## Migrations

- `app/database/migrations.py` maintains `schema_migrations`.
- Baseline version `1` for existing installs; no destructive upgrades yet.

## Errors

- Domain: `ValueError` with Persian messages from services.
- UI: `app/ui/error_handlers.py` — log + `QMessageBox` (adopt gradually in pages).

## Analytics

See `docs/ANALYTICS.md`. Snapshot rich tables: migration v2 (`docs/SNAPSHOT_PROPOSAL.md`).

## Insights

- Dashboard shows top 5 insights; full page with filters in sidebar
- Goal ROI in settings drives `goal_progress` rule
- See `docs/INSIGHTS.md`

