"""Dashboard page with metric cards and capital growth chart."""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView
from PySide6.QtCore import QThread, Qt, Signal, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.config import CURRENCY_USD, CURRENCY_USDT
from app.ui.widgets.growth_chart import populate_growth_chart
from app.ui.widgets.insight_list import InsightListWidget
from app.ui.widgets.metric_card import MetricCard
from app.ui.workers.quotes_worker import LiveQuotesWorker
from app.utils.dates import format_display_date, today_iso
from app.utils.i18n import t
from app.utils.money import format_money, format_number, format_pct


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label


class DashboardPage(QWidget):
    request_refresh = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._quotes_thread: QThread | None = None
        self.setObjectName("dashboardPage")

        # --- Hero: two primary KPIs ---
        self.card_value = MetricCard(t("total_value"), variant="hero")
        self.card_year_realized = MetricCard(t("year_realized_pnl"), variant="hero")

        hero = QFrame()
        hero.setObjectName("heroBand")
        hero_l = QHBoxLayout(hero)
        hero_l.setContentsMargins(0, 0, 0, 0)
        hero_l.setSpacing(16)
        hero_l.addWidget(self.card_value, 1)
        hero_l.addWidget(self.card_year_realized, 1)

        # --- Gold fund strip (always visible) ---
        self.card_gold_in = MetricCard(t("gold_in"), variant="compact")
        self.card_gold_out = MetricCard(t("gold_out"), variant="compact")
        self.card_gold_holding = MetricCard(t("gold_holding"), variant="compact")

        gold_block = QFrame()
        gold_block.setObjectName("goldFundStrip")
        gold_outer = QVBoxLayout(gold_block)
        gold_outer.setContentsMargins(0, 0, 0, 0)
        gold_outer.setSpacing(10)
        gold_outer.addWidget(_section_label(t("gold_fund")))
        gold_row = QHBoxLayout()
        gold_row.setContentsMargins(0, 0, 0, 0)
        gold_row.setSpacing(12)
        gold_row.addWidget(self.card_gold_in, 1)
        gold_row.addWidget(self.card_gold_out, 1)
        gold_row.addWidget(self.card_gold_holding, 1)
        gold_outer.addLayout(gold_row)

        # --- Details shell ---
        details = QFrame()
        details.setObjectName("detailsPanel")
        details_l = QVBoxLayout(details)
        details_l.setContentsMargins(0, 4, 0, 0)
        details_l.setSpacing(12)

        self.details_toggle = QToolButton()
        self.details_toggle.setObjectName("detailsToggle")
        self.details_toggle.setText(t("details"))
        self.details_toggle.setCheckable(True)
        self.details_toggle.setChecked(False)
        self.details_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.details_toggle.setArrowType(Qt.ArrowType.LeftArrow)
        self.details_toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.details_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.details_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_toggle.toggled.connect(self._on_details_toggled)
        details_l.addWidget(self.details_toggle)

        self.details_body = QWidget()
        self.details_body.setObjectName("detailsBody")
        body_l = QVBoxLayout(self.details_body)
        body_l.setContentsMargins(0, 2, 0, 0)
        body_l.setSpacing(18)

        # Performance KPIs
        self.card_pnl = MetricCard(t("total_pnl"), variant="compact")
        self.card_today = MetricCard(t("today_pnl"), variant="compact")
        self.card_return = MetricCard(t("return_pct"), variant="compact")
        self.card_realized = MetricCard(t("realized_pnl"), variant="compact")
        self.card_open = MetricCard(t("open_count"), variant="compact")
        self.card_closed = MetricCard(t("closed_count"), variant="compact")

        perf_block = QFrame()
        perf_block.setObjectName("detailBlock")
        perf_l = QVBoxLayout(perf_block)
        perf_l.setContentsMargins(0, 0, 0, 0)
        perf_l.setSpacing(10)
        perf_l.addWidget(_section_label(t("metrics_overview")))

        kpi_grid = QGridLayout()
        kpi_grid.setContentsMargins(0, 0, 0, 0)
        kpi_grid.setHorizontalSpacing(12)
        kpi_grid.setVerticalSpacing(12)
        kpi_grid.addWidget(self.card_pnl, 0, 0)
        kpi_grid.addWidget(self.card_today, 0, 1)
        kpi_grid.addWidget(self.card_return, 0, 2)
        kpi_grid.addWidget(self.card_realized, 1, 0)
        kpi_grid.addWidget(self.card_open, 1, 1)
        kpi_grid.addWidget(self.card_closed, 1, 2)
        for col in range(3):
            kpi_grid.setColumnStretch(col, 1)
        perf_l.addLayout(kpi_grid)
        body_l.addWidget(perf_block)

        # Market
        self.card_usdt = MetricCard(t("usdt_rate"), variant="ticker")
        self.card_gold = MetricCard(t("gold_rate"), variant="ticker")
        market_block = QFrame()
        market_block.setObjectName("detailBlock")
        market_outer = QVBoxLayout(market_block)
        market_outer.setContentsMargins(0, 0, 0, 0)
        market_outer.setSpacing(10)
        market_outer.addWidget(_section_label(t("market_rates")))
        market = QFrame()
        market.setObjectName("marketStrip")
        market_l = QHBoxLayout(market)
        market_l.setContentsMargins(0, 0, 0, 0)
        market_l.setSpacing(12)
        market_l.addWidget(self.card_usdt, 1)
        market_l.addWidget(self.card_gold, 1)
        market_outer.addWidget(market)
        body_l.addWidget(market_block)

        # Chart + side rail
        self.chart = QChart()
        self.chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        self.chart.legend().hide()
        self.chart.setTitle("")
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumHeight(340)
        self.chart_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        chart_frame = QFrame()
        chart_frame.setObjectName("chartPanel")
        chart_l = QVBoxLayout(chart_frame)
        chart_l.setContentsMargins(18, 16, 18, 14)
        chart_l.setSpacing(8)
        chart_l.addWidget(_section_label(t("capital_trend")))
        chart_l.addWidget(self.chart_view, 1)

        self.asset_summary = QFrame()
        self.asset_summary.setObjectName("sidePanel")
        self.asset_summary_layout = QVBoxLayout(self.asset_summary)
        self.asset_summary_layout.setContentsMargins(16, 16, 16, 16)
        self.asset_summary_layout.setSpacing(10)
        self.asset_summary_layout.addWidget(_section_label(t("asset_summary")))

        self._asset_scroll = QScrollArea()
        self._asset_scroll.setWidgetResizable(True)
        self._asset_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._asset_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._asset_scroll.setMinimumHeight(160)
        self._asset_inner = QWidget()
        self._asset_rows = QVBoxLayout(self._asset_inner)
        self._asset_rows.setContentsMargins(0, 0, 0, 0)
        self._asset_rows.setSpacing(8)
        self._asset_rows.addStretch()
        self._asset_scroll.setWidget(self._asset_inner)
        self.asset_list = QLabel(t("no_data"))
        self.asset_list.hide()
        self.asset_summary_layout.addWidget(self._asset_scroll, 1)

        self.perf_summary = QFrame()
        self.perf_summary.setObjectName("sidePanel")
        self.perf_layout = QVBoxLayout(self.perf_summary)
        self.perf_layout.setContentsMargins(16, 16, 16, 16)
        self.perf_layout.setSpacing(10)
        self.perf_layout.addWidget(_section_label(t("performance_summary")))
        self.perf_label = QLabel("")
        self.perf_label.setObjectName("bodyText")
        self.perf_label.setWordWrap(True)
        self.perf_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        self.perf_layout.addWidget(self.perf_label, 1)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(12)
        side.addWidget(self.asset_summary, 3)
        side.addWidget(self.perf_summary, 2)

        stage = QFrame()
        stage.setObjectName("detailStage")
        stage_l = QHBoxLayout(stage)
        stage_l.setContentsMargins(0, 0, 0, 0)
        stage_l.setSpacing(14)
        stage_l.addWidget(chart_frame, 5)
        stage_l.addLayout(side, 2)
        body_l.addWidget(stage, 1)

        # Insights
        insights_wrap = QFrame()
        insights_wrap.setObjectName("insightsWrap")
        iw_l = QVBoxLayout(insights_wrap)
        iw_l.setContentsMargins(18, 16, 18, 16)
        iw_l.setSpacing(8)
        self.insights_panel = InsightListWidget(show_title=True)
        self.insights_panel.setMinimumHeight(168)
        self.insights_panel.setMaximumHeight(240)
        iw_l.addWidget(self.insights_panel)
        body_l.addWidget(insights_wrap)

        self.details_body.setVisible(False)
        details_l.addWidget(self.details_body, 1)

        # Page shell
        body = QWidget()
        body.setObjectName("dashboardBody")
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(20)
        root.addWidget(hero)
        root.addWidget(gold_block)
        root.addWidget(details, 1)
        root.addStretch(0)

        scroll = QScrollArea()
        scroll.setObjectName("dashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)

        self._quotes_timer = QTimer(self)
        self._quotes_timer.timeout.connect(self._refresh_quotes_async)
        self._apply_quotes_timer()

    def _on_details_toggled(self, expanded: bool) -> None:
        self.details_body.setVisible(expanded)
        self.details_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.LeftArrow
        )

    def refresh(self) -> None:
        self.ctx.apply_price_api_settings()
        self._apply_quotes_timer()
        self.ctx.sync_live_prices_to_portfolio()
        self.ctx.portfolio.record_snapshot()
        dash = self.ctx.dashboard.build(
            calendar=self.ctx.settings.calendar,
            persist_growth=True,
        )
        series = dash.growth_series
        self._render_metrics(dash.metrics, series, dash.asset_summary)
        self._render_gold_fund(dash.gold_fund)
        self._render_usdt_card()
        self._render_gold_card()
        self._update_chart(series)
        self._render_insights()
        if self.ctx.settings.live_prices_enabled:
            self._refresh_quotes_async()

    def _render_insights(self) -> None:
        self.ctx.insights.set_goal_roi_pct(self.ctx.settings.goal_roi_pct)
        views = self.ctx.insights.list_insights(
            calendar=self.ctx.settings.calendar,
            limit=5,
        )
        self.insights_panel.set_insights(views)

    def _apply_quotes_timer(self) -> None:
        s = self.ctx.settings
        msec = max(15, int(s.price_refresh_seconds)) * 1000
        self._quotes_timer.setInterval(msec)
        if s.live_prices_enabled and (s.usdt_api_enabled or s.gold_api_enabled):
            if not self._quotes_timer.isActive():
                self._quotes_timer.start()
        else:
            self._quotes_timer.stop()

    def _clear_asset_rows(self) -> None:
        while self._asset_rows.count() > 1:
            item = self._asset_rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_asset_row(self, name: str, qty_text: str, value_text: str) -> None:
        row = QFrame()
        row.setObjectName("assetRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        name_l = QLabel(name)
        name_l.setObjectName("assetRowName")
        name_l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        meta = QLabel(qty_text)
        meta.setObjectName("mutedText")
        meta.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        val = QLabel(value_text)
        val.setObjectName("assetRowValue")
        val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(val)
        lay.addWidget(meta)
        lay.addStretch()
        lay.addWidget(name_l)
        self._asset_rows.insertWidget(self._asset_rows.count() - 1, row)

    def _render_gold_fund(self, gold) -> None:
        unit = t("gram_unit")

        def _g(value: float) -> str:
            v = float(value or 0.0)
            if abs(v) < 1e-9:
                return f"0 {unit}"
            if abs(v - round(v)) < 1e-6:
                return f"{format_number(round(v), 0)} {unit}"
            if abs(v) < 10:
                return f"{format_number(v, 4)} {unit}"
            return f"{format_number(v, 2)} {unit}"

        gold_in = float(gold.gold_in_g)
        gold_out = float(gold.gold_out_g)
        holding = float(getattr(gold, "gold_holding_g", gold.gold_debt_g))

        self.card_gold_in.set_value(_g(gold_in))
        self.card_gold_in.set_caption("")
        self.card_gold_out.set_value(_g(gold_out))
        self.card_gold_out.set_caption("")

        # موجودی = وارد − خارج؛ بدهی صندوق همان مانده است
        self.card_gold_holding.set_value(
            _g(holding),
            tone="negative" if holding > 1e-9 else None,
        )
        if holding > 1e-9:
            self.card_gold_holding.set_caption(t("gold_debt_caption"))
        else:
            self.card_gold_holding.set_caption("")

    def _render_metrics(
        self,
        m,
        series: list[tuple[str, float]] | None = None,
        asset_summary: list[tuple[str, float, float]] | None = None,
    ) -> None:
        currency = self.ctx.settings.currency
        calendar = self.ctx.settings.calendar
        money = self.ctx.money

        self.card_value.set_value(money(m.total_value))
        rate = self.ctx.fx.usdt_tmn
        if rate and currency not in (CURRENCY_USD, CURRENCY_USDT):
            usd_text = format_money(
                m.total_value,
                CURRENCY_USD,
                fx_rate=rate,
            )
            self.card_value.set_caption(f"≈ {usd_text}")
        else:
            self.card_value.set_caption("")

        year_pnl = float(getattr(m, "year_realized_pnl", 0.0) or 0.0)
        year_tone = (
            "positive" if year_pnl > 0 else ("negative" if year_pnl < 0 else None)
        )
        self.card_year_realized.set_value(
            money(year_pnl, show_sign=True),
            tone=year_tone,
        )
        year_key = getattr(m, "year_key", "") or ""
        self.card_year_realized.set_caption(year_key if year_key else "")

        pnl_tone = (
            "positive" if m.total_pnl > 0 else ("negative" if m.total_pnl < 0 else None)
        )
        self.card_pnl.set_value(money(m.total_pnl, show_sign=True), tone=pnl_tone)
        self.card_pnl.set_caption(format_pct(m.total_pnl_pct))

        realized_tone = (
            "positive"
            if m.realized_pnl > 0
            else ("negative" if m.realized_pnl < 0 else None)
        )
        self.card_realized.set_value(
            money(m.realized_pnl, show_sign=True),
            tone=realized_tone,
        )
        self.card_return.set_value(format_pct(m.annual_return_pct))
        self.card_open.set_value(str(m.open_count))
        self.card_closed.set_value(str(m.closed_count))

        today_tone = (
            "positive" if m.today_pnl > 0 else ("negative" if m.today_pnl < 0 else None)
        )
        self.card_today.set_value(money(m.today_pnl, show_sign=True), tone=today_tone)
        self.card_today.set_caption(format_pct(m.today_pnl_pct))

        self._clear_asset_rows()
        if asset_summary:
            for name, qty, val in asset_summary:
                self._add_asset_row(
                    name,
                    format_number(qty, 4 if qty < 10 else 0),
                    money(val),
                )
            self.asset_list.setText("")
        else:
            empty = QLabel(t("no_data"))
            empty.setObjectName("mutedText")
            empty.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._asset_rows.insertWidget(0, empty)
            self.asset_list.setText(t("no_data"))

        self.perf_label.setText(
            "\n".join(
                [
                    f"معاملات باز: {m.open_count}",
                    f"معاملات بسته: {m.closed_count}",
                    f"سود تحقق‌یافته: {money(m.realized_pnl, show_sign=True)}",
                    f"بیشترین سود: {money(m.max_profit, show_sign=True)}",
                    f"بیشترین ضرر: {money(m.max_loss, show_sign=True)}",
                    f"آپدیت: {format_display_date(today_iso(), calendar)}",
                ]
            )
        )

    def _render_usdt_card(self) -> None:
        s = self.ctx.settings
        if not s.live_prices_enabled or not s.usdt_api_enabled:
            rate = self.ctx.fx.usdt_tmn
            self.card_usdt.set_title(t("usdt_rate_offline"))
            if rate and rate > 0:
                self.card_usdt.set_value(f"{format_number(rate, 0)} تومان")
            else:
                self.card_usdt.set_value("غیرفعال")
            self.card_usdt.set_caption("")
            return
        cached = self.ctx.fx.cached
        rate = self.ctx.fx.usdt_tmn
        if rate and rate > 0:
            live = cached is not None and cached.fetched_at > 0
            title = t("usdt_rate") if live else t("usdt_rate_offline")
            self.card_usdt.set_title(title)
            self.card_usdt.set_value(f"{format_number(rate, 0)} تومان")
            self.card_usdt.set_caption("زنده" if live else "ذخیره‌شده")
        else:
            self.card_usdt.set_title(t("usdt_rate"))
            self.card_usdt.set_value("در حال دریافت…")
            self.card_usdt.set_caption("")

    def _render_gold_card(self) -> None:
        s = self.ctx.settings
        if not s.live_prices_enabled or not s.gold_api_enabled:
            price = self.ctx.market.gold_toman_per_gram
            self.card_gold.set_title(t("gold_rate_offline"))
            if price and price > 0:
                self.card_gold.set_value(f"{format_number(price, 0)} تومان / گرم")
            else:
                self.card_gold.set_value("غیرفعال")
            self.card_gold.set_caption("")
            return
        quote = self.ctx.market.gold
        price = self.ctx.market.gold_toman_per_gram
        if price and price > 0:
            live = quote is not None and quote.fetched_at > 0
            title = t("gold_rate") if live else t("gold_rate_offline")
            self.card_gold.set_title(title)
            self.card_gold.set_value(f"{format_number(price, 0)} تومان / گرم")
            if quote and quote.change_24h is not None:
                self.card_gold.set_caption(format_pct(quote.change_24h))
            else:
                self.card_gold.set_caption("زنده" if live else "ذخیره‌شده")
        else:
            self.card_gold.set_title(t("gold_rate"))
            self.card_gold.set_value("در حال دریافت…")
            self.card_gold.set_caption("")

    def _refresh_quotes_async(self) -> None:
        s = self.ctx.settings
        if not s.live_prices_enabled:
            return
        if not (s.usdt_api_enabled or s.gold_api_enabled):
            return
        if self._quotes_thread is not None and self._quotes_thread.isRunning():
            return
        thread = QThread(self)
        worker = LiveQuotesWorker(
            live_enabled=s.live_prices_enabled,
            usdt_enabled=s.usdt_api_enabled,
            gold_enabled=s.gold_api_enabled,
            wallex_url=s.wallex_markets_url,
            persian_url=s.persiantoolbox_url,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _on_done(payload: object) -> None:
            if isinstance(payload, dict):
                usdt = payload.get("usdt")
                gold = payload.get("gold")
                if isinstance(usdt, (int, float)) and usdt > 0:
                    self.ctx.fx.apply_fetched_rate(float(usdt), source="wallex")
                if isinstance(gold, (int, float)) and gold > 0:
                    ch = payload.get("gold_change_24h")
                    change = float(ch) if ch is not None else None
                    self.ctx.market.apply_fetched_gold(
                        float(gold), change_24h=change
                    )
            self.ctx.persist_live_quotes()
            updated = self.ctx.sync_live_prices_to_portfolio()
            if updated.get("total"):
                self.request_refresh.emit()
            self._render_usdt_card()
            self._render_gold_card()
            series = self.ctx.portfolio.growth_series(persist=False)
            dash = self.ctx.dashboard.build(
                calendar=self.ctx.settings.calendar,
                persist_growth=False,
                growth_series=series,
            )
            self._render_metrics(dash.metrics, series, dash.asset_summary)
            self._render_gold_fund(dash.gold_fund)
            self._update_chart(series)
            thread.quit()

        worker.finished.connect(thread.quit)
        worker.finished.connect(_on_done)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def _clear() -> None:
            self._quotes_thread = None

        thread.finished.connect(_clear)
        self._quotes_thread = thread
        thread.start()

    def _update_chart(self, series_data: list[tuple[str, float]] | None = None) -> None:
        if series_data is None:
            series_data = self.ctx.portfolio.growth_series(persist=False)
        populate_growth_chart(
            self.chart,
            series_data,
            theme=self.ctx.settings.theme,
            calendar=self.ctx.settings.calendar,
            title="",
        )
