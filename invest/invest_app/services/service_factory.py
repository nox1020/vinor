"""Construct application services with shared dependencies."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from invest_app.analytics.dashboard_provider import DashboardDataProvider
from invest_app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from invest_app.analytics.report_generator import AnalyticsReportGenerator
from invest_app.insights.engine import InvestmentInsightsEngine
from invest_app.insights.provider import InsightProvider
from invest_app.services.backup_service import BackupService
from invest_app.services.export_service import ExportService
from invest_app.services.fx_service import FxService
from invest_app.services.market_service import MarketService
from invest_app.services.portfolio_service import PortfolioService
from invest_app.services.report_service import ReportService
from invest_app.services.trade_service import TradeService


@dataclass
class AppServices:
    """Wire-up of domain services for one database connection."""

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


def build_services(conn: sqlite3.Connection, *, db_path: Path) -> AppServices:
    """Create services sharing a single PortfolioService instance."""
    portfolio = PortfolioService(conn)
    trades = TradeService(conn, portfolio=portfolio)
    analytics = PortfolioAnalyticsService(portfolio)
    insights_engine = InvestmentInsightsEngine()
    return AppServices(
        portfolio=portfolio,
        trades=trades,
        reports=ReportService(conn, portfolio=portfolio),
        backup=BackupService(db_path),
        export=ExportService(),
        fx=FxService(),
        market=MarketService(),
        analytics=analytics,
        dashboard=DashboardDataProvider(portfolio, analytics, trades),
        analytics_reports=AnalyticsReportGenerator(analytics),
        insights_engine=insights_engine,
        insights=InsightProvider(analytics, insights_engine),
    )
