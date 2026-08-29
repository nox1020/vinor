"""Close / sell trade dialog (supports partial close)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.models.trade import Trade
from app.ui.widgets.date_edit import DateEdit
from app.utils import calc
from app.utils.dates import format_short_date, parse_iso_date
from app.utils.i18n import t
from app.utils.money import format_money, format_pct, format_qty


class SellDialog(QDialog):
    def __init__(
        self,
        trade: Trade,
        calendar: str,
        currency: str,
        parent=None,
        *,
        fx_rate: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("sell"))
        self.setMinimumWidth(460)
        self._trade = trade
        self._currency = currency
        self._calendar = calendar
        self._fx_rate = fx_rate

        help_text = QLabel(
            "توضیح بستن معامله:\n"
            "• با بستن معامله، مقدار انتخاب‌شده از موجودی دارایی کم می‌شود.\n"
            "• سود یا زیان نهایی محاسبه و در «معاملات بسته» ثبت می‌شود.\n"
            "• می‌توانید فقط بخشی از مقدار را ببندید؛ باقی‌مانده باز می‌ماند.\n"
            "• این عمل قابل بازگشت خودکار نیست (مگر ثبت خرید دوباره)."
        )
        help_text.setObjectName("mutedText")
        help_text.setWordWrap(True)

        info = QLabel(
            f"دارایی: {trade.asset_name}\n"
            f"مقدار باز: {format_qty(trade.quantity)}\n"
            f"قیمت خرید: {self._fmt(trade.buy_price)}\n"
            f"تاریخ خرید: {format_short_date(trade.buy_date, calendar)}"
        )
        info.setObjectName("bodyText")
        info.setWordWrap(True)

        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0.00000001, max(trade.quantity, 0.00000001))
        self.quantity.setDecimals(8)
        self.quantity.setValue(trade.quantity)

        self.sell_price = QDoubleSpinBox()
        self.sell_price.setRange(0, 1e15)
        self.sell_price.setDecimals(8)
        self.sell_price.setValue(trade.current_price or trade.buy_price)

        self.fee = QDoubleSpinBox()
        self.fee.setRange(0, 1e15)
        self.fee.setDecimals(8)

        self.date = DateEdit(calendar)
        self.note = QLineEdit()
        self.note.setPlaceholderText("توضیح اختیاری برای این فروش...")

        self.preview = QLabel("")
        self.preview.setObjectName("bodyText")
        self.preview.setWordWrap(True)

        self.quantity.valueChanged.connect(self._update_preview)
        self.sell_price.valueChanged.connect(self._update_preview)
        self.fee.valueChanged.connect(self._update_preview)

        form = QFormLayout()
        form.addRow(t("quantity"), self.quantity)
        form.addRow(t("sell_price"), self.sell_price)
        form.addRow(t("fee"), self.fee)
        form.addRow(t("sell_date"), self.date)
        form.addRow(t("note"), self.note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("بستن معامله")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("cancel"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(help_text)
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        self._update_preview()

    def _fmt(self, value: float, *, show_sign: bool = False) -> str:
        return format_money(
            value,
            self._currency,
            show_sign=show_sign,
            fx_rate=self._fx_rate,
        )

    def _update_preview(self) -> None:
        qty = float(self.quantity.value())
        sell = float(self.sell_price.value())
        fee = float(self.fee.value())
        ratio = qty / self._trade.quantity if self._trade.quantity else 1.0
        buy_fee = self._trade.buy_fee * ratio
        pnl = calc.realized_pnl(qty, self._trade.buy_price, sell, buy_fee, fee)
        pct = calc.return_pct(qty, self._trade.buy_price, sell, buy_fee, fee)
        remain = max(0.0, self._trade.quantity - qty)
        self.preview.setText(
            f"سود/زیان برآوردی: {self._fmt(pnl, show_sign=True)} "
            f"({format_pct(pct)})\n"
            f"باقی‌مانده پس از بستن: {format_qty(remain)}"
        )
        self.preview.setObjectName(
            "summaryPositive" if pnl >= 0 else "summaryNegative"
        )
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)

    def _on_accept(self) -> None:
        if self.quantity.value() <= 0:
            QMessageBox.warning(self, t("error"), "مقدار فروش باید بزرگ‌تر از صفر باشد.")
            return
        if self.quantity.value() > self._trade.quantity + 1e-9:
            QMessageBox.warning(self, t("error"), "مقدار فروش از معامله باز بیشتر است.")
            return
        if self.sell_price.value() <= 0:
            QMessageBox.warning(self, t("error"), "قیمت فروش باید بزرگ‌تر از صفر باشد.")
            return
        try:
            sell_iso = self.date.iso_date()
            sell_d = parse_iso_date(sell_iso)
            buy_d = parse_iso_date(self._trade.buy_date)
        except Exception:
            QMessageBox.warning(self, t("error"), "تاریخ نامعتبر است.")
            return
        if sell_d < buy_d:
            QMessageBox.warning(
                self, t("error"), "تاریخ فروش نمی‌تواند قبل از تاریخ خرید باشد."
            )
            return

        qty = float(self.quantity.value())
        sell = float(self.sell_price.value())
        fee = float(self.fee.value())
        ratio = qty / self._trade.quantity if self._trade.quantity else 1.0
        buy_fee = self._trade.buy_fee * ratio
        pnl = calc.realized_pnl(qty, self._trade.buy_price, sell, buy_fee, fee)
        remain = max(0.0, self._trade.quantity - qty)
        partial = remain > 1e-9

        confirm_text = (
            f"آیا از بستن این معامله مطمئن هستید؟\n\n"
            f"دارایی: {self._trade.asset_name}\n"
            f"مقدار بستن: {format_qty(qty)}"
            f"{' (بستن جزئی)' if partial else ' (بستن کامل)'}\n"
            f"قیمت فروش: {self._fmt(sell)}\n"
            f"تاریخ فروش: {format_short_date(sell_iso, self._calendar)}\n"
            f"سود/زیان نهایی: {self._fmt(pnl, show_sign=True)}\n"
            f"باقی‌مانده باز: {format_qty(remain)}\n\n"
            f"پس از تأیید، موجودی دارایی کم می‌شود و رکورد در معاملات بسته ثبت می‌گردد."
        )
        confirm = QMessageBox.question(
            self,
            "تأیید بستن معامله",
            confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.accept()

    def payload(self) -> dict:
        return {
            "quantity": float(self.quantity.value()),
            "sell_price": float(self.sell_price.value()),
            "sell_fee": float(self.fee.value()),
            "sell_date": self.date.iso_date(),
            "sell_note": self.note.text().strip(),
        }
