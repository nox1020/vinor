"""Settings page: appearance, calendar, currency, price APIs, backup, export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap import AppContext
from app.config import (
    CALENDAR_LABELS,
    CALENDARS,
    CURRENCIES,
    CURRENCY_LABELS,
    DEFAULT_PERSIANTOOLBOX_URL,
    DEFAULT_WALLEX_MARKETS_URL,
    PRICE_REFRESH_OPTIONS,
    THEME_LABELS,
    THEMES,
)
from app.ui.dialogs.confirm import confirm_delete
from app.ui.error_handlers import show_user_error
from app.ui.workers.quotes_worker import QuotesTestWorker
from app.utils.i18n import t
from app.utils.money import format_number


class SettingsPage(QWidget):
    settings_changed = Signal()
    price_settings_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._loading = False
        self._test_thread: QThread | None = None

        self.calendar = QComboBox()
        for key in CALENDARS:
            self.calendar.addItem(CALENDAR_LABELS[key], key)

        self.currency = QComboBox()
        for key in CURRENCIES:
            self.currency.addItem(CURRENCY_LABELS[key], key)

        self.theme = QComboBox()
        for key in THEMES:
            self.theme.addItem(THEME_LABELS[key], key)

        self.calendar.currentIndexChanged.connect(self._auto_save)
        self.currency.currentIndexChanged.connect(self._auto_save)
        self.theme.currentIndexChanged.connect(self._auto_save)

        prefs = QGroupBox("تنظیمات ظاهری و واحدها")
        form = QFormLayout(prefs)
        form.addRow(t("calendar"), self.calendar)
        form.addRow(t("currency"), self.currency)
        form.addRow(t("theme"), self.theme)

        self.goal_roi = QLineEdit()
        self.goal_roi.setPlaceholderText("مثلاً ۱۵")
        self.goal_roi.editingFinished.connect(self._auto_save)
        form.addRow(t("goal_roi"), self.goal_roi)

        hint = QLabel("تغییرات بلافاصله ذخیره می‌شوند.")
        hint.setObjectName("mutedText")
        form.addRow("", hint)

        # --- Price APIs ---
        self.chk_live = QCheckBox("فعال‌سازی دریافت آنلاین قیمت‌ها")
        self.chk_usdt = QCheckBox("نرخ تتر / دلار از Wallex")
        self.chk_gold = QCheckBox("قیمت طلا از PersianToolbox")
        self.chk_gold_auto = QCheckBox(
            "به‌روزرسانی خودکار قیمت دارایی‌های طلا و تتر/دلار"
        )

        self.refresh_combo = QComboBox()
        for sec in PRICE_REFRESH_OPTIONS:
            label = f"{sec} ثانیه" if sec < 60 else f"{sec // 60} دقیقه"
            if sec == 60:
                label = "۱ دقیقه"
            elif sec == 120:
                label = "۲ دقیقه"
            elif sec == 300:
                label = "۵ دقیقه"
            elif sec == 30:
                label = "۳۰ ثانیه"
            self.refresh_combo.addItem(label, sec)

        self.wallex_url = QLineEdit()
        self.wallex_url.setPlaceholderText(DEFAULT_WALLEX_MARKETS_URL)
        self.pt_url = QLineEdit()
        self.pt_url.setPlaceholderText(DEFAULT_PERSIANTOOLBOX_URL)

        self.btn_reset_urls = QPushButton("بازنشانی آدرس‌ها")
        self.btn_reset_urls.setObjectName("secondaryBtn")
        self.btn_test_apis = QPushButton("بروزرسانی / تست الان")
        self.api_status = QLabel("")
        self.api_status.setObjectName("mutedText")
        self.api_status.setWordWrap(True)

        for w in (
            self.chk_live,
            self.chk_usdt,
            self.chk_gold,
            self.chk_gold_auto,
            self.refresh_combo,
        ):
            if isinstance(w, QCheckBox):
                w.stateChanged.connect(self._auto_save_prices)
            else:
                w.currentIndexChanged.connect(self._auto_save_prices)
        self.wallex_url.editingFinished.connect(self._auto_save_prices)
        self.pt_url.editingFinished.connect(self._auto_save_prices)
        self.btn_reset_urls.clicked.connect(self._reset_urls)
        self.btn_test_apis.clicked.connect(self._test_apis)
        self.chk_live.stateChanged.connect(self._sync_price_controls_enabled)

        api_box = QGroupBox("API قیمت‌ها")
        api_form = QFormLayout(api_box)
        api_form.addRow(self.chk_live)
        api_form.addRow(self.chk_usdt)
        api_form.addRow(self.chk_gold)
        api_form.addRow(self.chk_gold_auto)
        api_form.addRow("بازه بروزرسانی", self.refresh_combo)
        api_form.addRow("آدرس Wallex", self.wallex_url)
        api_form.addRow("آدرس PersianToolbox", self.pt_url)
        api_btns = QHBoxLayout()
        api_btns.addWidget(self.btn_test_apis)
        api_btns.addWidget(self.btn_reset_urls)
        api_btns.addStretch()
        api_form.addRow(api_btns)
        api_form.addRow(self.api_status)
        api_hint = QLabel(
            "تتر: Wallex (بازار ایران) — طلا: PersianToolbox (قیمت هر گرم)."
        )
        api_hint.setObjectName("mutedText")
        api_hint.setWordWrap(True)
        api_form.addRow(api_hint)

        self.btn_backup = QPushButton(t("backup"))
        self.btn_restore = QPushButton(t("restore"))
        self.btn_restore.setObjectName("secondaryBtn")
        self.btn_excel = QPushButton(t("export_excel"))
        self.btn_pdf = QPushButton(t("export_pdf"))
        self.btn_analytics_xlsx = QPushButton(t("export_analytics"))
        self.btn_analytics_csv = QPushButton(t("export_analytics_csv"))
        self.btn_analytics_xlsx.setObjectName("secondaryBtn")
        self.btn_analytics_csv.setObjectName("secondaryBtn")

        self.btn_backup.clicked.connect(self._backup)
        self.btn_restore.clicked.connect(self._restore)
        self.btn_excel.clicked.connect(self._export_excel)
        self.btn_pdf.clicked.connect(self._export_pdf)
        self.btn_analytics_xlsx.clicked.connect(self._export_analytics_excel)
        self.btn_analytics_csv.clicked.connect(self._export_analytics_csv)

        data_box = QGroupBox("پشتیبان‌گیری و خروجی")
        data_layout = QHBoxLayout(data_box)
        data_layout.addWidget(self.btn_backup)
        data_layout.addWidget(self.btn_restore)
        data_layout.addWidget(self.btn_excel)
        data_layout.addWidget(self.btn_pdf)
        data_layout.addWidget(self.btn_analytics_xlsx)
        data_layout.addWidget(self.btn_analytics_csv)
        data_layout.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(prefs)
        layout.addWidget(api_box)
        layout.addWidget(data_box)
        layout.addStretch()

        self.reload_fields()

    def reload_fields(self) -> None:
        self._loading = True
        try:
            s = self.ctx.settings
            self._set_combo(self.calendar, s.calendar)
            self._set_combo(self.currency, s.currency)
            self._set_combo(self.theme, s.theme)
            self.chk_live.setChecked(s.live_prices_enabled)
            self.chk_usdt.setChecked(s.usdt_api_enabled)
            self.chk_gold.setChecked(s.gold_api_enabled)
            self.chk_gold_auto.setChecked(s.gold_auto_update_assets)
            self._set_combo_data(self.refresh_combo, s.price_refresh_seconds)
            self.wallex_url.setText(s.wallex_markets_url)
            self.pt_url.setText(s.persiantoolbox_url)
            goal = s.goal_roi_pct
            self.goal_roi.setText("" if goal is None else str(goal))
            self._sync_price_controls_enabled()
            self._update_api_status_label()
        finally:
            self._loading = False

    def refresh(self) -> None:
        self.reload_fields()

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _set_combo_data(combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
        if combo.count():
            combo.setCurrentIndex(0)

    def _sync_price_controls_enabled(self) -> None:
        on = self.chk_live.isChecked()
        for w in (
            self.chk_usdt,
            self.chk_gold,
            self.chk_gold_auto,
            self.refresh_combo,
            self.wallex_url,
            self.pt_url,
            self.btn_reset_urls,
            self.btn_test_apis,
        ):
            w.setEnabled(on)
        if on:
            self.chk_gold_auto.setEnabled(self.chk_gold.isChecked())

    def _auto_save(self) -> None:
        if self._loading:
            return
        new_calendar = self.calendar.currentData()
        new_currency = self.currency.currentData()
        new_theme = self.theme.currentData()
        if not all((new_calendar, new_currency, new_theme)):
            return

        goal_raw = self.goal_roi.text().strip()
        if not goal_raw:
            goal_val = None
        else:
            try:
                goal_val = float(goal_raw.replace(",", "."))
            except ValueError:
                return

        changed = (
            self.ctx.settings.calendar != new_calendar
            or self.ctx.settings.currency != new_currency
            or self.ctx.settings.theme != new_theme
            or self.ctx.settings.goal_roi_pct != goal_val
        )
        if not changed:
            return

        self.ctx.settings.calendar = new_calendar
        self.ctx.settings.currency = new_currency
        self.ctx.settings.theme = new_theme
        self.ctx.settings.goal_roi_pct = goal_val
        self.ctx.settings.first_run_done = True
        self.ctx.save_settings()
        self.ctx.invalidate_caches()
        self.settings_changed.emit()

    def _auto_save_prices(self) -> None:
        if self._loading:
            return
        self._sync_price_controls_enabled()
        s = self.ctx.settings
        wallex = self.wallex_url.text().strip() or DEFAULT_WALLEX_MARKETS_URL
        pt = self.pt_url.text().strip() or DEFAULT_PERSIANTOOLBOX_URL
        refresh = self.refresh_combo.currentData()
        refresh_sec = int(refresh) if refresh else s.price_refresh_seconds

        new_vals = (
            self.chk_live.isChecked(),
            self.chk_usdt.isChecked(),
            self.chk_gold.isChecked(),
            self.chk_gold_auto.isChecked(),
            refresh_sec,
            wallex,
            pt,
        )
        old_vals = (
            s.live_prices_enabled,
            s.usdt_api_enabled,
            s.gold_api_enabled,
            s.gold_auto_update_assets,
            s.price_refresh_seconds,
            s.wallex_markets_url,
            s.persiantoolbox_url,
        )
        if new_vals == old_vals:
            return

        s.live_prices_enabled = new_vals[0]
        s.usdt_api_enabled = new_vals[1]
        s.gold_api_enabled = new_vals[2]
        s.gold_auto_update_assets = new_vals[3]
        s.price_refresh_seconds = new_vals[4]
        s.wallex_markets_url = new_vals[5]
        s.persiantoolbox_url = new_vals[6]
        self.ctx.save_settings()
        self.ctx.apply_price_api_settings()
        self._update_api_status_label()
        self.price_settings_changed.emit()

    def _reset_urls(self) -> None:
        self.wallex_url.setText(DEFAULT_WALLEX_MARKETS_URL)
        self.pt_url.setText(DEFAULT_PERSIANTOOLBOX_URL)
        self._auto_save_prices()

    def _update_api_status_label(self) -> None:
        parts: list[str] = []
        usdt = self.ctx.fx.usdt_tmn
        gold = self.ctx.market.gold_toman_per_gram
        if usdt:
            parts.append(f"تتر: {format_number(usdt, 0)} تومان")
        if gold:
            parts.append(f"طلا: {format_number(gold, 0)} تومان/گرم")
        if not self.ctx.settings.live_prices_enabled:
            parts.append("دریافت آنلاین خاموش است.")
        self.api_status.setText(" | ".join(parts) if parts else "نرخی ذخیره نشده است.")

    def _test_apis(self) -> None:
        if self._test_thread is not None and self._test_thread.isRunning():
            return
        self._auto_save_prices()
        self.btn_test_apis.setEnabled(False)
        self.api_status.setText("در حال دریافت…")
        s = self.ctx.settings
        thread = QThread(self)
        worker = QuotesTestWorker(
            live_enabled=s.live_prices_enabled,
            usdt_enabled=s.usdt_api_enabled,
            gold_enabled=s.gold_api_enabled,
            wallex_url=s.wallex_markets_url,
            persian_url=s.persiantoolbox_url,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _done(payload: object) -> None:
            try:
                if not isinstance(payload, dict):
                    self.api_status.setText("خطا در دریافت.")
                    return
                lines = []
                usdt = payload.get("usdt")
                gold = payload.get("gold")
                if isinstance(usdt, (int, float)) and usdt > 0:
                    self.ctx.fx.apply_fetched_rate(float(usdt), source="wallex")
                    lines.append(f"تتر: {format_number(float(usdt), 0)} تومان")
                elif self.ctx.settings.usdt_api_enabled:
                    lines.append("تتر: ناموفق")
                if isinstance(gold, (int, float)) and gold > 0:
                    self.ctx.market.apply_fetched_gold(float(gold))
                    lines.append(f"طلا: {format_number(float(gold), 0)} تومان/گرم")
                elif self.ctx.settings.gold_api_enabled:
                    lines.append("طلا: ناموفق")
                self.ctx.persist_live_quotes()
                updated = self.ctx.sync_live_prices_to_portfolio()
                total_upd = updated.get("total") or 0
                if total_upd:
                    lines.append(f"دارایی به‌روز شد: {total_upd}")
                errors = payload.get("errors") or []
                if errors:
                    lines.extend(str(e) for e in errors)
                self.api_status.setText(" | ".join(lines) if lines else "نتیجه‌ای نبود.")
                self.price_settings_changed.emit()
            finally:
                self.btn_test_apis.setEnabled(self.chk_live.isChecked())
                thread.quit()

        worker.finished.connect(thread.quit)
        worker.finished.connect(_done)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def _clear() -> None:
            self._test_thread = None
            self.btn_test_apis.setEnabled(self.chk_live.isChecked())

        thread.finished.connect(_clear)
        self._test_thread = thread
        thread.start()

    def _backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("backup"),
            "invest_backup.db",
            "SQLite (*.db)",
        )
        if not path:
            return
        try:
            self.ctx.backup.backup(Path(path))
            QMessageBox.information(self, t("backup"), t("success"))
        except Exception as exc:
            show_user_error(self, exc)

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("restore"),
            "",
            "SQLite (*.db)",
        )
        if not path:
            return
        if not confirm_delete(
            self,
            title=t("restore"),
            detail=(
                "بازیابی باعث جایگزینی کامل داده‌های فعلی می‌شود.\n"
                "اطلاعات فعلی از بین می‌رود.\n"
                "این عمل قابل بازگشت نیست."
            ),
        ):
            return
        try:
            try:
                self.ctx.conn.close()
            except Exception:
                pass
            self.ctx.backup.restore(Path(path))
            self.ctx.reconnect()
            QMessageBox.information(self, t("restore"), t("success"))
            self.settings_changed.emit()
        except Exception as exc:
            try:
                self.ctx.reconnect()
            except Exception:
                pass
            show_user_error(self, exc)

    def _export_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, t("export_excel"), "invest_report.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            self.ctx.export.export_excel(
                Path(path),
                assets=self.ctx.portfolio.assets.list_all(),
                open_trades=self.ctx.trades.trades.list_open(),
                closed_trades=self.ctx.trades.trades.list_closed(),
                calendar=self.ctx.settings.calendar,
                currency=self.ctx.settings.currency,
                fx_rate=self.ctx.fx.usdt_tmn,
            )
            QMessageBox.information(self, t("export_excel"), t("success"))
        except Exception as exc:
            show_user_error(self, exc)

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, t("export_pdf"), "invest_report.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            self.ctx.export.export_pdf(
                Path(path),
                assets=self.ctx.portfolio.assets.list_all(),
                open_trades=self.ctx.trades.trades.list_open(),
                closed_trades=self.ctx.trades.trades.list_closed(),
                calendar=self.ctx.settings.calendar,
                currency=self.ctx.settings.currency,
                title="گزارش سرمایه و معاملات",
                fx_rate=self.ctx.fx.usdt_tmn,
            )
            QMessageBox.information(self, t("export_pdf"), t("success"))
        except Exception as exc:
            show_user_error(self, exc)

    def _export_analytics_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("export_analytics"),
            "invest_analytics.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            from app.analytics.export import export_analytics_excel

            export_analytics_excel(
                Path(path),
                self.ctx.analytics_reports,
                calendar=self.ctx.settings.calendar,
            )
            QMessageBox.information(self, t("export_analytics"), t("success"))
        except Exception as exc:
            show_user_error(self, exc)

    def _export_analytics_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("export_analytics_csv"),
            "invest_analytics.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            from app.analytics.export import export_bundle_csv

            bundle = self.ctx.analytics.analyze(calendar=self.ctx.settings.calendar)
            export_bundle_csv(Path(path), bundle)
            QMessageBox.information(self, t("export_analytics_csv"), t("success"))
        except Exception as exc:
            show_user_error(self, exc)
