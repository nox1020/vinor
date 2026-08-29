"""Full insights page with category / severity filters."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.insights.categories import InsightCategory
from app.insights.severity import InsightSeverity
from app.ui.widgets.insight_list import InsightListWidget
from app.utils.i18n import t


class InsightsPage(QWidget):
    """Display-only insights browser; all logic lives in InsightProvider."""

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.category = QComboBox()
        self.severity = QComboBox()
        self.category.blockSignals(True)
        self.severity.blockSignals(True)
        self.category.addItem(t("all_categories"), None)
        for cat in InsightCategory:
            self.category.addItem(cat.value, cat)
        self.severity.addItem(t("all_severities"), None)
        for sev in InsightSeverity:
            self.severity.addItem(sev.label, sev)
        self.category.blockSignals(False)
        self.severity.blockSignals(False)

        self.category.currentIndexChanged.connect(self.refresh)
        self.severity.currentIndexChanged.connect(self.refresh)

        filters = QHBoxLayout()
        filters.addWidget(QLabel(t("insights_page")))
        filters.addStretch()
        filters.addWidget(self.category)
        filters.addWidget(self.severity)

        self.list = InsightListWidget()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(filters)
        layout.addWidget(self.list, 1)

    def refresh(self) -> None:
        self.ctx.insights.set_goal_roi_pct(self.ctx.settings.goal_roi_pct)
        cat = self.category.currentData()
        sev = self.severity.currentData()
        views = self.ctx.insights.list_insights(
            calendar=self.ctx.settings.calendar,
            category=cat,
            min_severity=sev,
        )
        self.list.set_insights(views)
