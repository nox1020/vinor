"""Main application window with collapsible sidebar navigation."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.config import APP_NAME
from app.ui.pages.asset_detail_page import AssetDetailPage
from app.ui.pages.assets_page import AssetsPage
from app.ui.pages.closed_trades_page import ClosedTradesPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.insights_page import InsightsPage
from app.ui.pages.open_trades_page import OpenTradesPage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.theme import apply_theme
from app.utils.dates import format_display_date, today_iso
from app.utils.i18n import t

_SIDEBAR_EXPANDED_W = 248
_SIDEBAR_COLLAPSED_W = 72
_SIDEBAR_ANIM_MS = 280


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.setMinimumSize(1024, 680)
        self._assets_nav_index = 1
        self._detail_index: int | None = None
        self._sidebar_expanded = False
        self._sidebar_anim: QParallelAnimationGroup | None = None

        root = QWidget()
        root.setObjectName("centralRoot")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setProperty("expanded", False)
        self.sidebar.setFixedWidth(_SIDEBAR_COLLAPSED_W)
        self._side_layout = QVBoxLayout(self.sidebar)
        self._side_layout.setContentsMargins(10, 14, 10, 14)
        self._side_layout.setSpacing(10)

        # --- Collapsed / expanded chrome ---
        self.mono = QLabel(APP_NAME or "V+")
        self.mono.setObjectName("sidebarMono")
        self.mono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mono.setFixedSize(44, 44)

        self.brand = QLabel(APP_NAME)
        self.brand.setObjectName("appBrand")
        self.brand.setWordWrap(True)
        self.brand.setVisible(False)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(10)
        brand_row.addWidget(self.mono, 0, Qt.AlignmentFlag.AlignTop)
        brand_row.addWidget(self.brand, 1)
        self._side_layout.addLayout(brand_row)

        self.sidebar_toggle = QPushButton("☰")
        self.sidebar_toggle.setObjectName("sidebarToggle")
        self.sidebar_toggle.setCheckable(True)
        self.sidebar_toggle.setChecked(False)
        self.sidebar_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_toggle.setToolTip(t("open_menu"))
        self.sidebar_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.sidebar_toggle.toggled.connect(self._on_sidebar_toggled)
        self._side_layout.addWidget(self.sidebar_toggle)

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        divider.setFixedHeight(1)
        self._side_layout.addWidget(divider)

        self.sidebar_nav = QWidget()
        self.sidebar_nav.setObjectName("sidebarNav")
        nav_layout = QVBoxLayout(self.sidebar_nav)
        nav_layout.setContentsMargins(0, 4, 0, 0)
        nav_layout.setSpacing(4)

        self._nav_opacity = QGraphicsOpacityEffect(self.sidebar_nav)
        self.sidebar_nav.setGraphicsEffect(self._nav_opacity)
        self._nav_opacity.setOpacity(0.0)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []

        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(ctx)
        self.assets = AssetsPage(ctx)
        self.open_trades = OpenTradesPage(ctx)
        self.closed_trades = ClosedTradesPage(ctx)
        self.reports = ReportsPage(ctx)
        self.insights_page = InsightsPage(ctx)
        self.settings = SettingsPage(ctx)
        self.asset_detail = AssetDetailPage(ctx)

        pages = [
            (t("dashboard"), self.dashboard),
            (t("assets"), self.assets),
            (t("open_trades"), self.open_trades),
            (t("closed_trades"), self.closed_trades),
            (t("reports"), self.reports),
            (t("insights_page"), self.insights_page),
            (t("settings"), self.settings),
        ]

        for index, (label, page) in enumerate(pages):
            btn = QPushButton(label)
            btn.setObjectName("sidebarNavBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(btn, index)
            self.nav_buttons.append(btn)
            nav_layout.addWidget(btn)
            self.stack.addWidget(page)

        self._detail_index = self.stack.addWidget(self.asset_detail)
        nav_layout.addStretch()
        self._side_layout.addWidget(self.sidebar_nav, 1)
        self.sidebar_nav.setVisible(False)

        self.nav_group.idClicked.connect(self._on_nav)
        self.nav_buttons[0].setChecked(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)

        self.title_label = QLabel(t("app_title"))
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("pageSubtitle")

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        content_layout.addWidget(header)
        content_layout.addWidget(self.stack, 1)

        outer.addWidget(self.sidebar)
        outer.addWidget(content, 1)

        self.assets.data_changed.connect(self.refresh_all)
        self.assets.open_detail.connect(self._open_asset_detail)
        self.open_trades.data_changed.connect(self.refresh_all)
        self.closed_trades.data_changed.connect(self.refresh_all)
        self.asset_detail.data_changed.connect(self.refresh_all)
        self.asset_detail.back_requested.connect(self._back_from_detail)
        self.settings.settings_changed.connect(self._on_settings_changed)
        self.settings.price_settings_changed.connect(self._on_price_settings_changed)
        self.dashboard.request_refresh.connect(self._on_live_prices_updated)

        self._update_header()
        self.refresh_all()

    def _sync_sidebar_chrome(self, expanded: bool) -> None:
        self.sidebar.setProperty("expanded", expanded)
        self.sidebar.style().unpolish(self.sidebar)
        self.sidebar.style().polish(self.sidebar)
        self.brand.setVisible(expanded)
        if expanded:
            self.sidebar_toggle.setText(f"✕  {t('close_menu')}")
            self.sidebar_toggle.setToolTip(t("close_menu"))
            self._side_layout.setContentsMargins(14, 18, 14, 18)
        else:
            self.sidebar_toggle.setText("☰")
            self.sidebar_toggle.setToolTip(t("open_menu"))
            self._side_layout.setContentsMargins(10, 14, 10, 14)

    def _animate_nav_opacity(self, target: float) -> None:
        anim = QPropertyAnimation(self._nav_opacity, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(self._nav_opacity.opacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._nav_fade = anim

    def _on_sidebar_toggled(self, expanded: bool) -> None:
        self._sidebar_expanded = expanded
        self._sync_sidebar_chrome(expanded)

        if self._sidebar_anim is not None:
            self._sidebar_anim.stop()

        start = self.sidebar.width()
        end = _SIDEBAR_EXPANDED_W if expanded else _SIDEBAR_COLLAPSED_W

        # Allow width to animate (clear fixed constraint)
        self.sidebar.setMinimumWidth(min(start, end))
        self.sidebar.setMaximumWidth(max(start, end))

        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self.sidebar, prop)
            anim.setDuration(_SIDEBAR_ANIM_MS)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(anim)

        if expanded:
            self.sidebar_nav.setVisible(True)
            self._animate_nav_opacity(1.0)
        else:
            self._animate_nav_opacity(0.0)

        def _finish() -> None:
            self.sidebar.setFixedWidth(end)
            if not expanded:
                self.sidebar_nav.setVisible(False)

        group.finished.connect(_finish)
        self._sidebar_anim = group
        group.start()

    def _on_nav(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        titles = [
            t("dashboard"),
            t("assets"),
            t("open_trades"),
            t("closed_trades"),
            t("reports"),
            t("insights_page"),
            t("settings"),
        ]
        self.title_label.setText(titles[index] if index else t("app_title"))
        self._update_header()
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _open_asset_detail(self, asset_id: int) -> None:
        self.asset_detail.show_asset(asset_id)
        if self._detail_index is not None:
            self.stack.setCurrentIndex(self._detail_index)
        self.nav_buttons[self._assets_nav_index].setChecked(True)
        asset = self.ctx.portfolio.assets.get(asset_id)
        name = asset.name if asset else t("asset_detail")
        self.title_label.setText(name)
        self._update_header()

    def _back_from_detail(self) -> None:
        self.stack.setCurrentIndex(self._assets_nav_index)
        self.nav_buttons[self._assets_nav_index].setChecked(True)
        self.title_label.setText(t("assets"))
        self._update_header()
        self.assets.refresh()

    def _update_header(self) -> None:
        cal = self.ctx.settings.calendar
        self.subtitle_label.setText(f"آپدیت: {format_display_date(today_iso(), cal)}")

    def refresh_all(self) -> None:
        self.ctx.reload_settings()
        self.ctx.insights.set_goal_roi_pct(self.ctx.settings.goal_roi_pct)
        self.ctx.invalidate_caches()
        self._update_header()
        current = self.stack.currentWidget()
        self.dashboard.refresh()
        for page in (
            self.assets,
            self.open_trades,
            self.closed_trades,
            self.reports,
            self.insights_page,
            self.settings,
            self.asset_detail,
        ):
            if page is current:
                page.refresh()
        if (
            self._detail_index is not None
            and self.stack.currentIndex() == self._detail_index
            and self.asset_detail._asset_id is not None
        ):
            asset = self.ctx.portfolio.assets.get(self.asset_detail._asset_id)
            if asset:
                self.title_label.setText(asset.name)

    def _on_settings_changed(self) -> None:
        self.ctx.reload_settings()
        self.ctx.insights.set_goal_roi_pct(self.ctx.settings.goal_roi_pct)
        self.ctx.apply_price_api_settings()
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.ctx.settings.theme)
        self.refresh_all()

    def _on_price_settings_changed(self) -> None:
        self.ctx.reload_settings()
        self.ctx.apply_price_api_settings()
        self.dashboard.refresh()
        self.assets.refresh()
        self.open_trades.refresh()
        if self.asset_detail._asset_id is not None:
            self.asset_detail.refresh()
        self.settings._update_api_status_label()

    def _on_live_prices_updated(self) -> None:
        """Refresh holdings pages after live gold/price sync (without full reload)."""
        self.assets.refresh()
        self.open_trades.refresh()
        if self.asset_detail._asset_id is not None:
            self.asset_detail.refresh()
