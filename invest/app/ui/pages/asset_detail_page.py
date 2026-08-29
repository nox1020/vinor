"""Asset detail page: summary + buy/sell history for one asset."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.config import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN
from app.models.asset import Asset
from app.ui.dialogs.asset_dialog import AssetDialog
from app.ui.dialogs.buy_dialog import BuyDialog
from app.ui.dialogs.confirm import confirm_delete
from app.ui.error_handlers import show_user_error
from app.ui.dialogs.sell_dialog import SellDialog
from app.ui.widgets.metric_card import MetricCard
from app.ui.widgets.searchable_table import SearchableTable
from app.utils import calc
from app.utils.dates import format_short_date
from app.utils.i18n import t
from app.utils.money import format_pct, format_qty


class AssetDetailPage(QWidget):
    data_changed = Signal()
    back_requested = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._asset_id: int | None = None

        self.btn_back = QPushButton(f"← {t('back')}")
        self.btn_back.setObjectName("secondaryBtn")
        self.btn_back.clicked.connect(self.back_requested.emit)

        self.title = QLabel(t("asset_detail"))
        self.title.setObjectName("sectionTitle")

        header = QHBoxLayout()
        header.addWidget(self.btn_back)
        header.addWidget(self.title, 1)

        self.card_qty = MetricCard(t("quantity"))
        self.card_avg = MetricCard(t("buy_price"))
        self.card_price = MetricCard(t("current_price"))
        self.card_value = MetricCard("ارزش کل")
        self.card_pnl = MetricCard(t("pnl"))
        self.card_pct = MetricCard(t("pnl_pct"))

        cards = QGridLayout()
        cards.setSpacing(12)
        cards.addWidget(self.card_qty, 0, 0)
        cards.addWidget(self.card_avg, 0, 1)
        cards.addWidget(self.card_price, 0, 2)
        cards.addWidget(self.card_value, 1, 0)
        cards.addWidget(self.card_pnl, 1, 1)
        cards.addWidget(self.card_pct, 1, 2)

        self.btn_buy = QPushButton(t("buy"))
        self.btn_close = QPushButton(t("sell"))
        self.btn_close.setObjectName("dangerBtn")
        self.btn_edit = QPushButton(t("edit_asset"))
        self.btn_edit.setObjectName("secondaryBtn")
        self.btn_delete_closed = QPushButton(t("delete_closed_trade"))
        self.btn_delete_closed.setObjectName("dangerBtn")

        self.btn_buy.clicked.connect(self._buy)
        self.btn_close.clicked.connect(self._close_selected)
        self.btn_edit.clicked.connect(self._edit)
        self.btn_delete_closed.clicked.connect(self._delete_closed)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.btn_buy)
        toolbar.addWidget(self.btn_close)
        toolbar.addWidget(self.btn_edit)
        toolbar.addWidget(self.btn_delete_closed)
        toolbar.addStretch()

        self.open_table = SearchableTable(
            [
                "#",
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
        self.closed_table = SearchableTable(
            [
                "#",
                t("buy_date"),
                t("sell_date"),
                t("quantity"),
                t("buy_price"),
                t("sell_price"),
                t("pnl"),
                t("pnl_pct"),
                t("holding_days"),
                t("note"),
            ]
        )

        self.open_table.table.doubleClicked.connect(lambda *_: self._close_selected())

        self.tabs = QTabWidget()
        self.tabs.addTab(self.open_table, t("open_positions"))
        self.tabs.addTab(self.closed_table, t("closed_history"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(cards)
        layout.addLayout(toolbar)
        layout.addWidget(self.tabs, 1)

    def show_asset(self, asset_id: int) -> None:
        self._asset_id = asset_id
        self.refresh()

    def refresh(self) -> None:
        if self._asset_id is None:
            return
        self.ctx.sync_live_prices_to_portfolio()
        asset = self.ctx.portfolio.assets.get(self._asset_id)
        if not asset:
            self.back_requested.emit()
            return
        self._fill_summary(asset)
        self._fill_trades(asset)

    def _fill_summary(self, asset: Asset) -> None:
        money = self.ctx.money
        label = asset.name if not asset.symbol else f"{asset.name} ({asset.symbol})"
        self.title.setText(label)

        self.card_qty.set_value(format_qty(asset.quantity))
        self.card_avg.set_value(money(asset.avg_buy_price))
        self.card_price.set_value(money(asset.current_price))
        self.card_value.set_value(money(asset.total_value))
        pnl_tone = (
            "positive"
            if asset.unrealized_pnl > 0
            else ("negative" if asset.unrealized_pnl < 0 else None)
        )
        self.card_pnl.set_value(
            money(asset.unrealized_pnl, show_sign=True),
            tone=pnl_tone,
        )
        self.card_pct.set_value(format_pct(asset.unrealized_pnl_pct), tone=pnl_tone)

    def _fill_trades(self, asset: Asset) -> None:
        money = self.ctx.money
        calendar = self.ctx.settings.calendar
        open_trades = self.ctx.trades.trades.list_by_asset(
            asset.id, TRADE_STATUS_OPEN  # type: ignore[arg-type]
        )
        closed_trades = self.ctx.trades.trades.list_by_asset(
            asset.id, TRADE_STATUS_CLOSED  # type: ignore[arg-type]
        )

        open_rows = []
        for i, tr in enumerate(open_trades, start=1):
            pnl = calc.unrealized_pnl(
                tr.quantity, tr.buy_price, tr.current_price, tr.buy_fee
            )
            pct = calc.unrealized_pnl_pct(
                tr.quantity, tr.buy_price, tr.current_price, tr.buy_fee
            )
            open_rows.append(
                [
                    str(i),
                    format_short_date(tr.buy_date, calendar),
                    format_qty(tr.quantity),
                    money(tr.buy_price),
                    money(tr.current_price),
                    money(tr.quantity * tr.current_price),
                    SearchableTable.colored_item(
                        money(pnl, show_sign=True), pnl
                    ),
                    SearchableTable.colored_item(format_pct(pct), pct),
                    money(tr.buy_fee),
                    tr.buy_note,
                ]
            )
        self.open_table.set_rows(open_rows, raw=open_trades)
        self.tabs.setTabText(
            0, f"{t('open_positions')} ({len(open_trades)})"
        )

        closed_rows = []
        for i, tr in enumerate(closed_trades, start=1):
            pnl = tr.realized_pnl or 0.0
            pct = tr.return_pct or 0.0
            closed_rows.append(
                [
                    str(i),
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
                    tr.sell_note or tr.buy_note,
                ]
            )
        self.closed_table.set_rows(closed_rows, raw=closed_trades)
        self.tabs.setTabText(
            1, f"{t('closed_history')} ({len(closed_trades)})"
        )

    def _current_asset(self) -> Asset | None:
        if self._asset_id is None:
            return None
        return self.ctx.portfolio.assets.get(self._asset_id)

    def _buy(self) -> None:
        self.ctx.sync_live_prices_to_portfolio()
        asset = self._current_asset()
        if not asset:
            return
        dlg = BuyDialog(
            [asset],
            self.ctx.settings.calendar,
            parent=self,
            preselect_asset_id=asset.id,
            lock_asset=True,
            usdt_tmn=self.ctx.fx.usdt_tmn,
            gold_tmn=self.ctx.market.gold_toman_per_gram,
        )
        if dlg.exec():
            try:
                self.ctx.trades.register_buy(**dlg.payload())
                self.data_changed.emit()
                self.refresh()
            except Exception as exc:
                show_user_error(self, exc)

    def _close_selected(self) -> None:
        self.ctx.sync_live_prices_to_portfolio()
        trade = self.open_table.selected_raw()
        if not trade:
            QMessageBox.information(
                self, t("open_positions"), "یک معامله باز را از جدول انتخاب کنید."
            )
            self.tabs.setCurrentIndex(0)
            return
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
                self.ctx.trades.close_trade(trade.id, **dlg.payload())
                self.data_changed.emit()
                self.refresh()
            except Exception as exc:
                show_user_error(self, exc)

    def _edit(self) -> None:
        asset = self._current_asset()
        if not asset:
            return
        dlg = AssetDialog(asset, parent=self)
        if dlg.exec():
            try:
                self.ctx.trades.update_asset(dlg.get_asset())
                self.data_changed.emit()
                self.refresh()
            except Exception as exc:
                show_user_error(self, exc)

    def _delete_closed(self) -> None:
        self.tabs.setCurrentIndex(1)
        trade = self.closed_table.selected_raw()
        if not trade:
            QMessageBox.information(
                self,
                t("closed_history"),
                "از تب تاریخچه بسته‌شده یک مورد را انتخاب کنید.",
            )
            return
        if not confirm_delete(
            self,
            title=t("delete_closed_trade"),
            detail=(
                f"این مورد از تاریخچه «{trade.asset_name}» حذف شود؟\n"
                "موجودی فعلی دارایی تغییر نمی‌کند.\n"
                "این عمل قابل بازگشت نیست."
            ),
        ):
            return
        try:
            self.ctx.trades.delete_closed_trade(trade.id)
            self.data_changed.emit()
            self.refresh()
        except Exception as exc:
            show_user_error(self, exc)
