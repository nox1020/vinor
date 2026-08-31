"""Shared confirmation dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm_delete(
    parent: QWidget | None,
    *,
    title: str,
    detail: str,
) -> bool:
    """Ask the user to confirm a destructive delete action."""
    message = f"آیا مطمئن هستید؟\n\n{detail}".strip()
    result = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes
