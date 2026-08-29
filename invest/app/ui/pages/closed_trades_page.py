"""Closed trades page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.ui.dialogs.confirm import confirm_delete
from app.ui.error_handlers import show_user_error
from app.ui.widgets.searchable_table import SearchableTable
from app.utils.dates import format_short_date
from app.utils.i18n import t
from app.utils.money import format_pct, format_qty


class ClosedTradesPage(QWidget):
    data_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.summary = QLabel("")
        self.summary.setObjectName("summaryPositive")

        self.btn_delete = QPushButton(t("delete_closed_trade"))
        self.btn_delete.setObjectName("dangerBtn")
        self.btn_delete.clicked.connect(self._delete_selected)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.btn_delete)
        toolbar.addStretch()

        self.table = SearchableTable(
            [
                "#",
                "دارایی",
                t("buy_date"),
                t("sell_date"),
                t("quantity"),
                t("buy_price"),
                t("sell_price"),
                t("pnl"),
                t("pnl_pct"),
                t("holding_days"),
            ]
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.summary)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        money = self.ctx.money
        calendar = self.ctx.settings.calendar
        trades = self.ctx.trades.trades.list_closed()
        rows = []
        total_pnl = 0.0
        for i, tr in enumerate(trades, start=1):
            pnl = tr.realized_pnl or 0.0
            pct = tr.return_pct or 0.0
            total_pnl += pnl
            rows.append(
                [
                    str(i),
                    tr.asset_name,
                    format_short_date(tr.buy_date, calendar),
                    format_short_date(tr.sell_date, calendar),
                    format_qty(tr.quantity),
                    money(tr.buy_price),
                    money(tr.sell_price or 0),
                    SearchableTable.colored_item(
                        money(pnl, show_sign=True), pnl
                    ),
                    SearchableTable.colored_item(format_pct(pct), pct),
                    str(tr.holding_days or 0),
                ]
            )
        self.table.set_rows(rows, raw=trades)
        self.summary.setText(
            f"جمع سود / زیان تحقق‌یافته: {money(total_pnl, show_sign=True)}"
        )
        self.summary.setObjectName(
            "summaryPositive" if total_pnl >= 0 else "summaryNegative"
        )
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self.summary.update()

    def _delete_selected(self) -> None:
        trade = self.table.selected_raw()
        if not trade:
            QMessageBox.information(
                self, t("closed_trades"), "یک معامله بسته را انتخاب کنید."
            )
            return
        if not confirm_delete(
            self,
            title=t("delete_closed_trade"),
            detail=(
                f"تاریخچه معامله «{trade.asset_name}» حذف شود؟\n"
                "این کار فقط از سوابق حذف می‌کند و موجودی فعلی را تغییر نمی‌دهد.\n"
                "این عمل قابل بازگشت نیست."
            ),
        ):
            return
        try:
            self.ctx.trades.delete_closed_trade(trade.id)
            self.data_changed.emit()
        except Exception as exc:
            show_user_error(self, exc)
