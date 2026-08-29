"""Assets management page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.ui.dialogs.asset_dialog import AssetDialog
from app.ui.dialogs.confirm import confirm_delete
from app.ui.error_handlers import show_user_error
from app.ui.widgets.searchable_table import SearchableTable
from app.utils.i18n import t
from app.utils.money import format_pct, format_qty


class AssetsPage(QWidget):
    data_changed = Signal()
    open_detail = Signal(int)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.table = SearchableTable(
            [
                t("name"),
                t("symbol"),
                t("quantity"),
                t("buy_price"),
                t("current_price"),
                "ارزش کل",
                t("pnl"),
                t("pnl_pct"),
            ]
        )

        self.btn_add = QPushButton(t("add_asset"))
        self.btn_open = QPushButton(t("asset_detail"))
        self.btn_edit = QPushButton(t("edit_asset"))
        self.btn_edit.setObjectName("secondaryBtn")
        self.btn_delete = QPushButton(t("delete_asset"))
        self.btn_delete.setObjectName("dangerBtn")

        self.btn_add.clicked.connect(self._add)
        self.btn_open.clicked.connect(self._open_detail)
        self.btn_edit.clicked.connect(self._edit)
        self.btn_delete.clicked.connect(self._delete)
        self.table.table.doubleClicked.connect(lambda *_: self._open_detail())

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_open)
        toolbar.addWidget(self.btn_edit)
        toolbar.addWidget(self.btn_delete)
        toolbar.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        self.ctx.sync_live_prices_to_portfolio()
        money = self.ctx.money
        assets = self.ctx.portfolio.assets.list_all()
        rows = []
        for a in assets:
            rows.append(
                [
                    a.name,
                    a.symbol,
                    format_qty(a.quantity),
                    money(a.avg_buy_price),
                    money(a.current_price),
                    money(a.total_value),
                    SearchableTable.colored_item(
                        money(a.unrealized_pnl, show_sign=True),
                        a.unrealized_pnl,
                    ),
                    SearchableTable.colored_item(
                        format_pct(a.unrealized_pnl_pct), a.unrealized_pnl_pct
                    ),
                ]
            )
        self.table.set_rows(rows, raw=assets)

    def _open_detail(self) -> None:
        asset = self.table.selected_raw()
        if not asset or asset.id is None:
            QMessageBox.information(self, t("assets"), "یک دارایی را انتخاب کنید.")
            return
        self.open_detail.emit(int(asset.id))

    def _add(self) -> None:
        dlg = AssetDialog(parent=self)
        if dlg.exec():
            asset = dlg.get_asset()
            try:
                self.ctx.trades.create_asset(
                    name=asset.name,
                    symbol=asset.symbol,
                    quantity=asset.quantity,
                    avg_buy_price=asset.avg_buy_price,
                    current_price=asset.current_price,
                    notes=asset.notes,
                )
                self.data_changed.emit()
            except Exception as exc:
                show_user_error(self, exc)

    def _edit(self) -> None:
        asset = self.table.selected_raw()
        if not asset:
            QMessageBox.information(self, t("assets"), "یک دارایی را انتخاب کنید.")
            return
        dlg = AssetDialog(asset, parent=self)
        if dlg.exec():
            updated = dlg.get_asset()
            try:
                self.ctx.trades.update_asset(updated)
                self.data_changed.emit()
            except Exception as exc:
                show_user_error(self, exc)

    def _delete(self) -> None:
        asset = self.table.selected_raw()
        if not asset:
            QMessageBox.information(self, t("assets"), "یک دارایی را انتخاب کنید.")
            return
        if not confirm_delete(
            self,
            title=t("delete_asset"),
            detail=(
                f"دارایی «{asset.name}» حذف شود؟\n"
                "در صورت وجود معاملات بسته‌شده، تاریخچه آن‌ها نیز حذف می‌شود.\n"
                "این عمل قابل بازگشت نیست."
            ),
        ):
            return
        try:
            self.ctx.trades.delete_asset(asset.id)
            self.data_changed.emit()
        except Exception as exc:
            show_user_error(self, exc)
