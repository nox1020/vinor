"""Pages package."""

from app.ui.pages.asset_detail_page import AssetDetailPage
from app.ui.pages.assets_page import AssetsPage
from app.ui.pages.closed_trades_page import ClosedTradesPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.open_trades_page import OpenTradesPage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.settings_page import SettingsPage

__all__ = [
    "AssetDetailPage",
    "AssetsPage",
    "ClosedTradesPage",
    "DashboardPage",
    "OpenTradesPage",
    "ReportsPage",
    "SettingsPage",
]
