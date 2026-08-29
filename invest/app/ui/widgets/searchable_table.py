"""Table widget with search box and sorting."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import pnl_color
from app.utils.i18n import t

_PNL_MARK = "__pnl__"


class SearchableTable(QWidget):
    def __init__(self, headers: list[str], parent=None) -> None:
        super().__init__(parent)
        self._all_rows: list[list] = []
        self._raw: list = []
        self._headers = headers

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)

        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            len(headers) - 1, QHeaderView.ResizeMode.Stretch
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(self.search)
        layout.addLayout(top)
        layout.addWidget(self.table)

    def set_rows(self, rows: list[list], *, raw: list | None = None) -> None:
        """Set display rows. Optional `raw` parallel list stored as row UserRole."""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.table.setSortingEnabled(False)
        self._all_rows = rows
        self._raw = list(raw) if raw is not None else [None] * len(rows)
        self._render(self._all_rows, self._raw)
        self.table.setSortingEnabled(True)

    def selected_raw(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        self.table.setSortingEnabled(False)
        if not text:
            self._render(self._all_rows, self._raw)
            self.table.setSortingEnabled(True)
            return
        filtered_rows = []
        filtered_raw = []
        for row, payload in zip(self._all_rows, self._raw):
            hay = " ".join(self._cell_text(c) for c in row).lower()
            if text in hay:
                filtered_rows.append(row)
                filtered_raw.append(payload)
        self._render(filtered_rows, filtered_raw)
        self.table.setSortingEnabled(True)

    def _render(self, rows: list[list], raw: list) -> None:
        self.table.clearContents()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            payload = raw[r] if r < len(raw) else None
            for c, value in enumerate(row):
                item = self._make_item(value)
                if c == 0 and payload is not None:
                    item.setData(Qt.ItemDataRole.UserRole, payload)
                self.table.setItem(r, c, item)

    @staticmethod
    def _cell_text(value) -> str:
        if isinstance(value, tuple) and value and value[0] == _PNL_MARK:
            return str(value[1])
        if isinstance(value, QTableWidgetItem):
            return value.text()
        return str(value)

    @staticmethod
    def _make_item(value) -> QTableWidgetItem:
        if isinstance(value, tuple) and value and value[0] == _PNL_MARK:
            _, text, pnl_value = value
            item = QTableWidgetItem(str(text))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(pnl_color(pnl_value))
            # Numeric sort support when text starts with + / digits
            item.setData(Qt.ItemDataRole.UserRole + 1, float(pnl_value))
            return item
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        return item

    @staticmethod
    def colored_item(text: str, value: float) -> tuple:
        """Return a PnL-colored cell marker (safe to re-render / filter)."""
        return (_PNL_MARK, text, float(value))
