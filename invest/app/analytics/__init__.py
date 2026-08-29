"""Analytics package — investment analytics engine."""

from app.analytics.dashboard_provider import DashboardDataProvider
from app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from app.analytics.report_generator import AnalyticsReportGenerator

__all__ = [
    "DashboardDataProvider",
    "PortfolioAnalyticsService",
    "AnalyticsReportGenerator",
]
