"""First-run setup wizard for calendar, currency, and theme."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from app.config import (
    CALENDAR_LABELS,
    CALENDARS,
    CURRENCIES,
    CURRENCY_LABELS,
    THEME_LABELS,
    THEMES,
)
from app.models.settings import AppSettings
from app.utils.i18n import t


class FirstRunWizard(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("welcome_title"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self._settings = settings

        title = QLabel(t("welcome_title"))
        title.setObjectName("wizardTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel(t("welcome_subtitle"))
        subtitle.setObjectName("wizardSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.calendar = QComboBox()
        for key in CALENDARS:
            self.calendar.addItem(CALENDAR_LABELS[key], key)
        idx = list(CALENDARS).index(settings.calendar) if settings.calendar in CALENDARS else 0
        self.calendar.setCurrentIndex(idx)

        self.currency = QComboBox()
        for key in CURRENCIES:
            self.currency.addItem(CURRENCY_LABELS[key], key)
        idx = list(CURRENCIES).index(settings.currency) if settings.currency in CURRENCIES else 0
        self.currency.setCurrentIndex(idx)

        self.theme = QComboBox()
        for key in THEMES:
            self.theme.addItem(THEME_LABELS[key], key)
        idx = list(THEMES).index(settings.theme) if settings.theme in THEMES else 0
        self.theme.setCurrentIndex(idx)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow(t("calendar"), self.calendar)
        form.addRow(t("currency"), self.currency)
        form.addRow(t("theme"), self.theme)

        buttons = QDialogButtonBox()
        start_btn = buttons.addButton(t("continue"), QDialogButtonBox.ButtonRole.AcceptRole)
        start_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_settings(self) -> AppSettings:
        # Preserve price-API and other prefs; only change wizard fields.
        updated = AppSettings.from_dict(self._settings.to_dict())
        updated.calendar = self.calendar.currentData()
        updated.currency = self.currency.currentData()
        updated.theme = self.theme.currentData()
        updated.first_run_done = True
        return updated
