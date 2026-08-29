"""Create / edit asset dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from app.models.asset import Asset
from app.utils.i18n import t


class AssetDialog(QDialog):
    def __init__(self, asset: Asset | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("edit_asset") if asset else t("add_asset"))
        self.setMinimumWidth(400)
        self._asset = asset
        editing = asset is not None

        self.name = QLineEdit(asset.name if asset else "")
        self.symbol = QLineEdit(asset.symbol if asset else "")
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 1e15)
        self.quantity.setDecimals(8)
        self.quantity.setValue(asset.quantity if asset else 0)

        self.avg_buy = QDoubleSpinBox()
        self.avg_buy.setRange(0, 1e15)
        self.avg_buy.setDecimals(4)
        self.avg_buy.setValue(asset.avg_buy_price if asset else 0)

        self.current = QDoubleSpinBox()
        self.current.setRange(0, 1e15)
        self.current.setDecimals(4)
        self.current.setValue(asset.current_price if asset else 0)

        self.notes = QTextEdit()
        self.notes.setPlainText(asset.notes if asset else "")
        self.notes.setFixedHeight(80)

        # Editing inventory via this dialog desyncs open trades — lock when editing
        if editing:
            self.quantity.setReadOnly(True)
            self.avg_buy.setReadOnly(True)
            self.quantity.setToolTip("مقدار از طریق معاملات به‌روز می‌شود.")
            self.avg_buy.setToolTip("میانگین خرید از طریق معاملات محاسبه می‌شود.")

        form = QFormLayout()
        form.addRow(t("name"), self.name)
        form.addRow(t("symbol"), self.symbol)
        form.addRow(t("quantity"), self.quantity)
        form.addRow(t("buy_price"), self.avg_buy)
        form.addRow(t("current_price"), self.current)
        form.addRow(t("note"), self.notes)

        layout = QVBoxLayout(self)
        if editing:
            hint = QLabel("برای تغییر مقدار، از بخش معاملات باز استفاده کنید.")
            hint.setObjectName("mutedText")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("cancel"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, t("error"), "نام دارایی الزامی است.")
            return
        if self._asset is None and self.quantity.value() > 0 and self.avg_buy.value() <= 0:
            QMessageBox.warning(
                self, t("error"), "برای موجودی اولیه، قیمت خرید را وارد کنید."
            )
            return
        self.accept()

    def get_asset(self) -> Asset:
        base = self._asset or Asset(id=None, name="")
        base.name = self.name.text().strip()
        base.symbol = self.symbol.text().strip()
        if self._asset is None:
            base.quantity = float(self.quantity.value())
            base.avg_buy_price = float(self.avg_buy.value())
        base.current_price = float(self.current.value())
        base.notes = self.notes.toPlainText().strip()
        return base
