"""Date editor that supports Jalali or Gregorian calendars."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSpinBox, QWidget

from app.config import CALENDAR_JALALI
from app.utils.dates import (
    gregorian_parts,
    iso_from_parts,
    jalali_parts,
    parse_iso_date,
)

_JALALI_MONTHS = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]

_GREGORIAN_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


class DateEdit(QWidget):
    """Simple Y/M/D selector respecting the selected calendar system."""

    def __init__(self, calendar: str = CALENDAR_JALALI, parent=None) -> None:
        super().__init__(parent)
        self._calendar = calendar

        self.year = QSpinBox()
        self.month = QComboBox()
        self.day = QSpinBox()
        self.day.setRange(1, 31)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.day)
        layout.addWidget(self.month)
        layout.addWidget(self.year)

        self.month.currentIndexChanged.connect(self._refresh_day_range)
        self.year.valueChanged.connect(self._refresh_day_range)
        self.set_calendar(calendar)
        self.set_date(date.today())

    def set_calendar(self, calendar: str) -> None:
        self._calendar = calendar
        self.month.blockSignals(True)
        self.month.clear()
        if calendar == CALENDAR_JALALI:
            self.year.setRange(1300, 1500)
            self.month.addItems(_JALALI_MONTHS)
        else:
            self.year.setRange(1970, 2100)
            self.month.addItems(_GREGORIAN_MONTHS)
        self.month.blockSignals(False)
        self._refresh_day_range()

    def set_date(self, value: date | str | None) -> None:
        if value is None:
            value = date.today()
        elif isinstance(value, str):
            value = parse_iso_date(value)
        if self._calendar == CALENDAR_JALALI:
            y, m, d = jalali_parts(value)
        else:
            y, m, d = gregorian_parts(value)
        self.year.blockSignals(True)
        self.month.blockSignals(True)
        self.day.blockSignals(True)
        self.year.setValue(y)
        self.month.setCurrentIndex(m - 1)
        self._refresh_day_range()
        self.day.setValue(d)
        self.year.blockSignals(False)
        self.month.blockSignals(False)
        self.day.blockSignals(False)

    def iso_date(self) -> str:
        year = self.year.value()
        month = self.month.currentIndex() + 1
        day = self.day.value()
        if self._calendar == CALENDAR_JALALI:
            import jdatetime

            # Raises if the Jalali date is invalid
            jdatetime.date(year, month, day)
        return iso_from_parts(year, month, day, self._calendar)

    def qdate(self) -> QDate:
        d = parse_iso_date(self.iso_date())
        return QDate(d.year, d.month, d.day)

    def _refresh_day_range(self) -> None:
        month = self.month.currentIndex() + 1
        year = self.year.value()
        if month < 1:
            return
        if self._calendar == CALENDAR_JALALI:
            import jdatetime

            if month <= 6:
                max_day = 31
            elif month <= 11:
                max_day = 30
            else:
                try:
                    jdatetime.date(year, 12, 30)
                    max_day = 30
                except ValueError:
                    max_day = 29
        else:
            if month in (1, 3, 5, 7, 8, 10, 12):
                max_day = 31
            elif month == 2:
                leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                max_day = 29 if leap else 28
            else:
                max_day = 30
        current = self.day.value()
        self.day.setRange(1, max_day)
        if current > max_day:
            self.day.setValue(max_day)
