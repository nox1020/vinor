"""UI helpers for consistent error reporting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

from app.exceptions import InvestError
from app.utils.i18n import t

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


def show_user_error(parent: QWidget | None, exc: BaseException) -> None:
    """Log the exception and show a QMessageBox with a safe message."""
    if isinstance(exc, InvestError):
        logger.warning("User-facing error: %s", exc)
        message = str(exc)
    elif isinstance(exc, ValueError):
        logger.warning("Validation error: %s", exc)
        message = str(exc)
    else:
        logger.exception("Unexpected error")
        message = str(exc) or t("error")

    QMessageBox.warning(parent, t("error"), message)


def show_user_message(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    icon: QMessageBox.Icon = QMessageBox.Icon.Information,
) -> None:
    """Informational dialog with optional icon."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(icon)
    box.exec()
