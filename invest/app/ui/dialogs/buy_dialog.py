"""Register buy / open trade dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.models.asset import Asset
from app.ui.widgets.date_edit import DateEdit
from app.utils.i18n import t


class BuyDialog(QDialog):
    def __init__(
        self,
        assets: list[Asset],
        calendar: str,
        parent=None,
        *,
        preselect_asset_id: int | None = None,
        lock_asset: bool = False,
        usdt_tmn: float | None = None,
        gold_tmn: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("buy"))
        self.setMinimumWidth(440)
        self._assets = assets
        self._usdt_tmn = usdt_tmn
        self._gold_tmn = gold_tmn

        self.asset_combo = QComboBox()
        if not lock_asset:
            self.asset_combo.addItem("— دارایی جدید —", None)
        for asset in assets:
            label = asset.name if not asset.symbol else f"{asset.name} ({asset.symbol})"
            self.asset_combo.addItem(label, asset.id)

        self.new_name = QLineEdit()
        self.new_symbol = QLineEdit()

        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0.00000001, 1e15)
        self.quantity.setDecimals(8)
        self.quantity.setValue(1)

        self.buy_price = QDoubleSpinBox()
        self.buy_price.setRange(0, 1e15)
        self.buy_price.setDecimals(8)

        self.current_price = QDoubleSpinBox()
        self.current_price.setRange(0, 1e15)
        self.current_price.setDecimals(8)

        self.fee = QDoubleSpinBox()
        self.fee.setRange(0, 1e15)
        self.fee.setDecimals(8)

        self.date = DateEdit(calendar)
        self.note = QLineEdit()

        self.asset_combo.currentIndexChanged.connect(self._on_asset_changed)

        form = QFormLayout()
        form.addRow("دارایی", self.asset_combo)
        if not lock_asset:
            form.addRow(t("name"), self.new_name)
            form.addRow(t("symbol"), self.new_symbol)
        form.addRow(t("quantity"), self.quantity)
        form.addRow(t("buy_price"), self.buy_price)
        form.addRow(t("current_price"), self.current_price)
        form.addRow(t("fee"), self.fee)
        form.addRow(t("date"), self.date)
        form.addRow(t("note"), self.note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("cancel"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if preselect_asset_id is not None:
            for i in range(self.asset_combo.count()):
                if self.asset_combo.itemData(i) == preselect_asset_id:
                    self.asset_combo.setCurrentIndex(i)
                    break
        if lock_asset:
            self.asset_combo.setEnabled(False)
        self._on_asset_changed()

    def _on_asset_changed(self) -> None:
        from app.services.trade_service import TradeService

        is_new = self.asset_combo.currentData() is None
        self.new_name.setEnabled(is_new)
        self.new_symbol.setEnabled(is_new)
        asset_id = self.asset_combo.currentData()
        if asset_id is not None:
            asset = next((a for a in self._assets if a.id == asset_id), None)
            if asset:
                live = TradeService.live_unit_price(
                    asset.name,
                    asset.symbol,
                    usdt_tmn=self._usdt_tmn,
                    gold_tmn=self._gold_tmn,
                )
                px = live or asset.current_price or asset.avg_buy_price
                self.buy_price.setValue(px)
                self.current_price.setValue(live or asset.current_price or px)

    def _on_accept(self) -> None:
        if self.asset_combo.currentData() is None and not self.new_name.text().strip():
            QMessageBox.warning(self, t("error"), "نام دارایی الزامی است.")
            return
        if self.quantity.value() <= 0:
            QMessageBox.warning(self, t("error"), "مقدار باید بزرگ‌تر از صفر باشد.")
            return
        if self.buy_price.value() <= 0:
            QMessageBox.warning(self, t("error"), "قیمت خرید باید بزرگ‌تر از صفر باشد.")
            return
        try:
            self.date.iso_date()
        except Exception:
            QMessageBox.warning(self, t("error"), "تاریخ نامعتبر است.")
            return
        self.accept()

    def payload(self) -> dict:
        asset_id = self.asset_combo.currentData()
        current = self.current_price.value()
        return {
            "asset_id": asset_id,
            "name": None if asset_id is not None else self.new_name.text().strip(),
            "symbol": "" if asset_id is not None else self.new_symbol.text().strip(),
            "quantity": float(self.quantity.value()),
            "buy_price": float(self.buy_price.value()),
            "buy_fee": float(self.fee.value()),
            "buy_date": self.date.iso_date(),
            "buy_note": self.note.text().strip(),
            "current_price": float(current) if current > 0 else None,
        }
