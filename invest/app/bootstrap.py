"""Application bootstrap: database, settings, shared services."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from app.config import DB_PATH, SETTING_GOLD_TMN_PER_GRAM, SETTING_USDT_TMN_RATE
from app.database.connection import get_connection, init_database
from app.database.migrations import ensure_default_settings, run_migrations
from app.models.settings import AppSettings
from app.repositories.settings_repo import SettingsRepository
from app.analytics.dashboard_provider import DashboardDataProvider
from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from app.analytics.report_generator import AnalyticsReportGenerator
from app.insights.engine import InvestmentInsightsEngine
from app.insights.provider import InsightProvider
from app.services.backup_service import BackupService
from app.services.export_service import ExportService
from app.services.fx_service import FxService
from app.services.market_service import MarketService
from app.services.portfolio_service import PortfolioService
from app.services.report_service import ReportService
from app.services.service_factory import AppServices, build_services
from app.services.trade_service import TradeService
from app.utils.money import format_money

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Shared runtime dependencies for the UI layer."""

    conn: sqlite3.Connection
    settings: AppSettings
    settings_repo: SettingsRepository
    portfolio: PortfolioService
    trades: TradeService
    reports: ReportService
    backup: BackupService
    export: ExportService
    fx: FxService
    market: MarketService
    analytics: PortfolioAnalyticsService
    dashboard: DashboardDataProvider
    analytics_reports: AnalyticsReportGenerator
    insights_engine: InvestmentInsightsEngine
    insights: InsightProvider

    def money(
        self,
        value: float,
        *,
        show_sign: bool = False,
        decimals: int | None = None,
        convert: bool = True,
    ) -> str:
        """Format amount in the active display currency (toman base + live FX)."""
        return format_money(
            value,
            self.settings.currency,
            show_sign=show_sign,
            decimals=decimals,
            fx_rate=self.fx.usdt_tmn,
            convert=convert,
        )

    def reload_settings(self) -> AppSettings:
        self.settings = self.settings_repo.load()
        return self.settings

    def save_settings(self, settings: AppSettings | None = None) -> None:
        if settings is not None:
            self.settings = settings
        self.settings_repo.save(self.settings)

    def apply_price_api_settings(self) -> None:
        """Push price-API preferences into live quote services."""
        s = self.settings
        live = s.live_prices_enabled
        self.fx.enabled = live and s.usdt_api_enabled
        self.fx.markets_url = s.wallex_markets_url
        self.fx.cache_seconds = float(s.price_refresh_seconds)
        self.market.enabled = live and s.gold_api_enabled
        self.market.api_url = s.persiantoolbox_url
        self.market.cache_seconds = float(s.price_refresh_seconds)

    def persist_live_quotes(self) -> None:
        rate = self.fx.usdt_tmn
        if rate and rate > 0:
            self.settings_repo.set(SETTING_USDT_TMN_RATE, f"{rate:.4f}")
        gold = self.market.gold_toman_per_gram
        if gold and gold > 0:
            self.settings_repo.set(SETTING_GOLD_TMN_PER_GRAM, f"{gold:.4f}")

    def sync_live_prices_to_portfolio(self) -> dict[str, int]:
        """
        Apply cached/live USDT & gold rates to matching assets so all
        value/PnL calculations use market prices.
        """
        s = self.settings
        if not s.live_prices_enabled:
            return {"usdt": 0, "gold": 0, "total": 0}
        return self.trades.apply_live_market_prices(
            usdt_tmn=self.fx.usdt_tmn if s.usdt_api_enabled else None,
            gold_tmn=self.market.gold_toman_per_gram if s.gold_api_enabled else None,
            update_usdt=s.usdt_api_enabled and s.gold_auto_update_assets,
            update_gold=s.gold_api_enabled and s.gold_auto_update_assets,
        )

    def invalidate_caches(self) -> None:
        """Clear analytics/insights caches after portfolio data changes."""
        self.analytics.invalidate_cache()
        self.insights_engine.invalidate_cache()
        self.dashboard.invalidate()

    def persist_fx_rate(self) -> None:
        """Backward-compatible alias."""
        self.persist_live_quotes()

    def close(self) -> None:
        self.conn.close()

    def reconnect(self) -> None:
        """Re-open DB connection and rebuild services (e.g. after restore)."""
        try:
            self.conn.close()
        except Exception as exc:
            logger.debug("Close before reconnect: %s", exc)
        init_database(DB_PATH)
        self.conn = get_connection(DB_PATH)
        run_migrations(self.conn)
        ensure_default_settings(self.conn)
        self.settings_repo = SettingsRepository(self.conn)
        self.settings = self.settings_repo.load()
        services = build_services(self.conn, db_path=DB_PATH)
        self._apply_services(services)
        self._seed_live_quotes()
        self.apply_price_api_settings()

    def _apply_services(self, services: AppServices) -> None:
        self.portfolio = services.portfolio
        self.trades = services.trades
        self.reports = services.reports
        self.backup = services.backup
        self.export = services.export
        self.fx = services.fx
        self.market = services.market
        self.analytics = services.analytics
        self.dashboard = services.dashboard
        self.analytics_reports = services.analytics_reports
        self.insights_engine = services.insights_engine
        self.insights = services.insights

    def _seed_live_quotes(self) -> None:
        raw_usdt = self.settings_repo.get(SETTING_USDT_TMN_RATE)
        if raw_usdt:
            try:
                self.fx.seed(float(raw_usdt), source="saved")
            except ValueError:
                logger.warning("Invalid saved USDT rate: %r", raw_usdt)
        raw_gold = self.settings_repo.get(SETTING_GOLD_TMN_PER_GRAM)
        if raw_gold:
            try:
                self.market.seed_gold(float(raw_gold), source="saved")
            except ValueError:
                logger.warning("Invalid saved gold rate: %r", raw_gold)


def bootstrap() -> AppContext:
    """Initialize database and build the application context."""
    init_database(DB_PATH)
    conn = get_connection(DB_PATH)
    run_migrations(conn)
    ensure_default_settings(conn)
    settings_repo = SettingsRepository(conn)
    settings = settings_repo.load()
    services = build_services(conn, db_path=DB_PATH)
    ctx = AppContext(
        conn=conn,
        settings=settings,
        settings_repo=settings_repo,
        portfolio=services.portfolio,
        trades=services.trades,
        reports=services.reports,
        backup=services.backup,
        export=services.export,
        fx=services.fx,
        market=services.market,
        analytics=services.analytics,
        dashboard=services.dashboard,
        analytics_reports=services.analytics_reports,
        insights_engine=services.insights_engine,
        insights=services.insights,
    )
    ctx._seed_live_quotes()
    ctx.apply_price_api_settings()
    return ctx
