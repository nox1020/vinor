#!/usr/bin/env python3
"""Entry point for the offline Investment & Trading Manager."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path


def _show_fatal_error(message: str) -> None:
    """Show a visible error even when launched with pythonw (no console)."""
    text = message.strip() or "خطای ناشناخته هنگام راه‌اندازی."
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        from app.config import APP_NAME

        QMessageBox.critical(None, APP_NAME, text)
        return
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            from app.config import APP_NAME

            ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def _install_excepthook() -> None:
    def _hook(exc_type, exc, tb) -> None:
        logging.getLogger(__name__).error(
            "Uncaught exception", exc_info=(exc_type, exc, tb)
        )
        brief = "".join(traceback.format_exception_only(exc_type, exc)).strip()
        _show_fatal_error(f"خطای پیش‌بینی‌نشده:\n{brief}")

    sys.excepthook = _hook


def main() -> int:
    try:
        from app.logging_config import setup_logging

        setup_logging()
    except Exception as exc:
        _show_fatal_error(f"راه‌اندازی لاگ ناموفق بود:\n{exc}")
        return 1

    _install_excepthook()

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from app.bootstrap import bootstrap
        from app.config import APP_NAME
        from app.ui.dialogs.first_run_wizard import FirstRunWizard
        from app.ui.main_window import MainWindow
        from app.ui.theme import apply_theme
    except Exception as exc:
        logging.getLogger(__name__).exception("Import failed during startup")
        _show_fatal_error(
            "بارگذاری برنامه ناموفق بود.\n"
            "وابستگی‌ها را در .venv نصب کنید:\n"
            "  .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n\n"
            f"{exc}"
        )
        return 1

    try:
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setOrganizationName("InvestManager")
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        icon_path = Path(__file__).resolve().parent / "assets" / "app.ico"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))

        ctx = bootstrap()
        apply_theme(app, ctx.settings.theme)

        if not ctx.settings.first_run_done:
            wizard = FirstRunWizard(ctx.settings)
            if wizard.exec():
                ctx.save_settings(wizard.result_settings())
                apply_theme(app, ctx.settings.theme)
            else:
                ctx.settings.first_run_done = True
                ctx.save_settings()

        window = MainWindow(ctx)
        window.show()
        code = app.exec()
        ctx.close()
        return int(code)
    except Exception as exc:
        logging.getLogger(__name__).exception("Startup failed")
        _show_fatal_error(f"برنامه راه‌اندازی نشد:\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
