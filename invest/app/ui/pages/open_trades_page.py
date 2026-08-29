"""Open trades page."""

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
from app.ui.dialogs.buy_dialog import BuyDialog
from app.ui.dialogs.sell_dialog import SellDialog
from app.ui.error_handlers import show_user_error
from app.ui.widgets.searchable_table import SearchableTable
from app.utils import calc
from app.utils.dates import format_short_date
from app.utils.i18n import t
from app.utils.money import format_pct, format_qty


class OpenTradesPage(QWidget):
    data_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.table = SearchableTable(
            [
                "#",
                "دارایی",
                t("buy_date"),
                t("quantity"),
                t("buy_price"),
                t("current_price"),
                "ارزش فعلی",
                t("pnl"),
                t("pnl_pct"),
                t("fee"),
                t("note"),
            ]
        )

        self.btn_buy = QPushButton(t("buy"))
        self.btn_close = QPushButton(t("sell"))
        self.btn_close.setObjectName("dangerBtn")

        self.btn_buy.clicked.connect(self._buy)
        self.btn_close.clicked.connect(self._close)
        self.table.table.doubleClicked.connect(lambda *_: self._close())

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.btn_buy)
        toolbar.addWidget(self.btn_close)
        toolbar.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        self.ctx.sync_live_prices_to_portfolio()
        money = self.ctx.money
        calendar = self.ctx.settings.calendar
        trades = self.ctx.trades.trades.list_open()
        rows = []
        for i, tr in enumerate(trades, start=1):
            pnl = calc.unrealized_pnl(tr.quantity, tr.buy_price, tr.current_price, tr.buy_fee)
            pct = calc.unrealized_pnl_pct(tr.quantity, tr.buy_price, tr.current_price, tr.buy_fee)
            value = tr.quantity * tr.current_price
            rows.append(
                [
                    str(i),
                    tr.asset_name,
                    format_short_date(tr.buy_date, calendar),
                    format_qty(tr.quantity),
                    money(tr.buy_price),
                    money(tr.current_price),
                    money(value),
                    SearchableTable.colored_item(
                        money(pnl, show_sign=True), pnl
                    ),
                    SearchableTable.colored_item(format_pct(pct), pct),
                    money(tr.buy_fee),
                    tr.buy_note,
                ]
            )
        self.table.set_rows(rows, raw=trades)

    def _buy(self) -> None:
        self.ctx.sync_live_prices_to_portfolio()
        assets = self.ctx.portfolio.assets.list_all()
        dlg = BuyDialog(
            assets,
            self.ctx.settings.calendar,
            parent=self,
            usdt_tmn=self.ctx.fx.usdt_tmn,
            gold_tmn=self.ctx.market.gold_toman_per_gram,
        )
        if dlg.exec():
            try:
                self.ctx.trades.register_buy(**dlg.payload())
                self.data_changed.emit()
            except Exception as exc:
                show_user_error(self, exc)

    def _close(self) -> None:
        self.ctx.sync_live_prices_to_portfolio()
        trade = self.table.selected_raw()
        if not trade:
            QMessageBox.information(self, t("open_trades"), "یک معامله را انتخاب کنید.")
            return
        # Reload trade so current_price reflects live gold/USDT.
        trade = self.ctx.trades.trades.get(trade.id) or trade
        dlg = SellDialog(
            trade,
            self.ctx.settings.calendar,
            self.ctx.settings.currency,
            parent=self,
            fx_rate=self.ctx.fx.usdt_tmn,
        )
        if dlg.exec():
            try:
                payload = dlg.payload()
                self.ctx.trades.close_trade(trade.id, **payload)
                self.data_changed.emit()
            except Exception as exc:
                show_user_error(self, exc)
