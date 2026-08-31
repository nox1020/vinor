"""Analytics package — investment analytics engine."""

from invest_app.analytics.dashboard_provider import DashboardDataProvider
from invest_app.analytics.portfolio_analytics_service import PortfolioAnalyticsService
from invest_app.analytics.report_generator import AnalyticsReportGenerator

__all__ = [
    "DashboardDataProvider",
    "PortfolioAnalyticsService",
    "AnalyticsReportGenerator",
]
