"""Metric summary card widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout


class MetricCard(QFrame):
    """KPI card. Variants: default, hero, compact, ticker."""

    def __init__(
        self,
        title: str,
        parent=None,
        *,
        variant: str = "default",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("variant", variant)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        if variant == "hero":
            layout.setContentsMargins(28, 24, 28, 24)
            layout.setSpacing(10)
            self.setMinimumHeight(148)
        elif variant == "ticker":
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(4)
            self.setMinimumHeight(72)
        elif variant == "compact":
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(6)
            self.setMinimumHeight(96)
        else:
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.value_label = QLabel("—")
        self.value_label.setObjectName("cardValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.value_label.setWordWrap(True)

        self.caption_label = QLabel("")
        self.caption_label.setObjectName("cardCaption")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.caption_label.setWordWrap(True)
        self.caption_label.hide()

        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.value_label)
        layout.addWidget(self.caption_label)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_caption(self, text: str = "") -> None:
        self.caption_label.setText(text)
        self.caption_label.setVisible(bool(text))

    def set_value(self, text: str, *, tone: str | None = None) -> None:
        self.value_label.setText(text)
        self.value_label.setProperty("tone", tone or "")
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)
        self.value_label.update()
        self.style().unpolish(self)
        self.style().polish(self)
