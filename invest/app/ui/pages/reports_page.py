"""Reports page fed by Analytics (single source of truth)."""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.ui.widgets.growth_chart import populate_growth_chart
from app.ui.widgets.metric_card import MetricCard
from app.ui.widgets.searchable_table import SearchableTable
from app.utils.i18n import t


class ReportsPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.card_realized = MetricCard("سود تحقق‌یافته")
        self.card_max_profit = MetricCard("بیشترین سود")
        self.card_max_loss = MetricCard("بیشترین ضرر")
        self.card_open = MetricCard(t("open_count"))
        self.card_closed = MetricCard(t("closed_count"))

        cards = QGridLayout()
        cards.setSpacing(12)
        cards.addWidget(self.card_realized, 0, 0)
        cards.addWidget(self.card_max_profit, 0, 1)
        cards.addWidget(self.card_max_loss, 0, 2)
        cards.addWidget(self.card_open, 0, 3)
        cards.addWidget(self.card_closed, 0, 4)

        self.daily_table = SearchableTable(["بازه", "تعداد", "سود / زیان", "نرخ موفقیت"])
        self.monthly_table = SearchableTable(["بازه", "تعداد", "سود / زیان", "نرخ موفقیت"])
        self.yearly_table = SearchableTable(["بازه", "تعداد", "سود / زیان", "نرخ موفقیت"])

        tabs = QTabWidget()
        tabs.addTab(self.daily_table, "سود روزانه")
        tabs.addTab(self.monthly_table, "سود ماهانه")
        tabs.addTab(self.yearly_table, "سود سالانه")

        self.chart = QChart()
        self.chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        self.chart.legend().hide()
        self.chart.setTitle("نمودار عملکرد")
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumHeight(260)
        chart_frame = QFrame()
        chart_frame.setObjectName("metricCard")
        chart_l = QVBoxLayout(chart_frame)
        chart_l.addWidget(self.chart_view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(cards)
        layout.addWidget(tabs, 1)
        layout.addWidget(chart_frame)

    def refresh(self) -> None:
        self.ctx.sync_live_prices_to_portfolio()
        calendar = self.ctx.settings.calendar
        # Prefer analytics engine; keep ReportService as fallback shape via performance report.
        perf = self.ctx.analytics_reports.performance_report(calendar=calendar)
        summary = self.ctx.analytics_reports.portfolio_summary(calendar=calendar)
        money = self.ctx.money

        realized = summary.capital.realized_pnl
        self.card_realized.set_value(
            money(realized, show_sign=True),
            tone="positive" if realized > 0 else ("negative" if realized < 0 else None),
        )
        tr = summary.trades
        if tr.closed_trades:
            self.card_max_profit.set_value(
                money(tr.max_profit, show_sign=True),
                tone="positive" if tr.max_profit > 0 else None,
            )
            self.card_max_loss.set_value(
                money(tr.max_loss, show_sign=True),
                tone="negative" if tr.max_loss < 0 else None,
            )
        else:
            self.card_max_profit.set_value("—")
            self.card_max_loss.set_value("—")
        self.card_open.set_value(str(tr.open_trades))
        self.card_closed.set_value(str(tr.closed_trades))

        self._fill_period_table(self.daily_table, perf.periods.get("daily", []))
        self._fill_period_table(self.monthly_table, perf.periods.get("monthly", []))
        self._fill_period_table(self.yearly_table, perf.periods.get("yearly", []))
        self._update_chart(perf.growth_series)

    def _fill_period_table(self, table: SearchableTable, items) -> None:
        money = self.ctx.money
        rows = []
        for item in items:
            rows.append(
                [
                    item.key,
                    str(item.trade_count),
                    SearchableTable.colored_item(
                        money(item.net_pnl, show_sign=True), item.net_pnl
                    ),
                    f"{item.success_rate_pct:.0f}%",
                ]
            )
        table.set_rows(rows)

    def _update_chart(self, growth: list[tuple[str, float]]) -> None:
        populate_growth_chart(
            self.chart,
            growth,
            theme=self.ctx.settings.theme,
            calendar=self.ctx.settings.calendar,
            title="نمودار عملکرد",
        )
