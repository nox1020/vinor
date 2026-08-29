"""Compact list of top insights for dashboard (display-only)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.insights.models import InsightViewModel
from app.utils.i18n import t


class InsightListWidget(QWidget):
    """Renders precomputed InsightViewModel rows — no analytics in the widget."""

    def __init__(self, parent=None, *, show_title: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("insightPanel")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(10)

        if show_title:
            header = QHBoxLayout()
            title = QLabel(t("insights"))
            title.setObjectName("sectionTitle")
            header.addWidget(title)
            header.addStretch()
            self._root.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setObjectName("insightScroll")

        self._inner = QWidget()
        self._inner.setObjectName("insightInner")
        self._list = QVBoxLayout(self._inner)
        self._list.setContentsMargins(0, 0, 2, 0)
        self._list.setSpacing(8)
        self._list.addStretch()
        self._scroll.setWidget(self._inner)
        self._root.addWidget(self._scroll, 1)

        self._empty = QLabel(t("no_insights"))
        self._empty.setObjectName("mutedText")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        self._list.insertWidget(0, self._empty)

    def set_insights(self, items: list[InsightViewModel]) -> None:
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not items:
            self._empty = QLabel(t("no_insights"))
            self._empty.setObjectName("mutedText")
            self._empty.setWordWrap(True)
            self._list.insertWidget(0, self._empty)
            return

        for view in items:
            self._list.insertWidget(self._list.count() - 1, self._card(view))

    def _card(self, view: InsightViewModel) -> QFrame:
        frame = QFrame()
        frame.setObjectName("insightCard")
        frame.setProperty("severity", view.severity)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        badge = QLabel(view.severity)
        badge.setObjectName("insightBadge")
        badge.setProperty("severity", view.severity)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(badge)
        top.addStretch()

        head = QLabel(view.title)
        head.setObjectName("insightTitle")
        head.setWordWrap(True)
        head.setAlignment(Qt.AlignmentFlag.AlignRight)

        body = QLabel(view.description)
        body.setObjectName("insightBody")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignRight)

        action = QLabel(view.action)
        action.setObjectName("insightAction")
        action.setWordWrap(True)
        action.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout.addLayout(top)
        layout.addWidget(head)
        layout.addWidget(body)
        layout.addWidget(action)

        # polish dynamic properties
        for w in (frame, badge):
            w.style().unpolish(w)
            w.style().polish(w)
        return frame
