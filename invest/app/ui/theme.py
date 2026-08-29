"""Theme loading helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QBrush, QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from app.config import STYLES_DIR, THEME_DARK, THEME_LIGHT

_current_theme: str = THEME_DARK


def current_theme() -> str:
    return _current_theme


def theme_is_dark(theme: str | None = None) -> bool:
    return (theme if theme is not None else _current_theme) == THEME_DARK


def theme_colors(theme: str | None = None) -> dict[str, str]:
    name = theme if theme is not None else _current_theme
    if theme_is_dark(name):
        return {
            "bg": "#0F1A15",
            "card": "#16241D",
            "text": "#E6F0EA",
            "muted": "#9BB5A8",
            "axis": "#9BB5A8",
            "title": "#F2FBF6",
            "grid": "#243830",
            "line": "#3DDB7E",
            "positive": "#3DDB7E",
            "negative": "#FF6B6B",
            "neutral": "#F2FBF6",
        }
    return {
        "bg": "#F0F3F1",
        "card": "#FFFFFF",
        "text": "#1A2E24",
        "muted": "#4A6358",
        "axis": "#4A6358",
        "title": "#102820",
        "grid": "#D0DCD5",
        "line": "#15803D",
        "positive": "#15803D",
        "negative": "#B91C1C",
        "neutral": "#102820",
    }


def pnl_color(value: float, theme: str | None = None) -> QColor:
    """Foreground color for profit/loss numbers on the active (or given) theme."""
    colors = theme_colors(theme)
    if value > 0:
        return QColor(colors["positive"])
    if value < 0:
        return QColor(colors["negative"])
    return QColor(colors["neutral"])


def apply_theme(app: QApplication, theme: str) -> None:
    """Load and apply a QSS theme plus matching application palette."""
    global _current_theme
    _current_theme = theme if theme in (THEME_DARK, THEME_LIGHT) else THEME_DARK

    name = "dark.qss" if _current_theme == THEME_DARK else "light.qss"
    path: Path = STYLES_DIR / name
    if not path.exists():
        path = STYLES_DIR / "dark.qss"
    qss = path.read_text(encoding="utf-8") if path.exists() else ""
    app.setStyleSheet(qss)

    colors = theme_colors(_current_theme)
    palette = QPalette()
    text = QColor(colors["text"])
    bg = QColor(colors["bg"])
    card = QColor(colors["card"])
    muted = QColor(colors["muted"])

    palette.setColor(QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, card)
    palette.setColor(QPalette.ColorRole.AlternateBase, bg)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, card)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    palette.setColor(QPalette.ColorRole.ToolTipBase, card)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1F5A42"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)


def style_chart(chart, theme: str) -> None:
    """Apply readable title/axis colors to a QChart for the active theme."""
    colors = theme_colors(theme)
    chart.setBackgroundBrush(QBrush(QColor("transparent")))
    chart.setTitleBrush(QBrush(QColor(colors["title"])))
    font = QFont()
    font.setBold(True)
    font.setPointSize(11)
    chart.setTitleFont(font)
    for axis in chart.axes():
        axis.setLabelsBrush(QBrush(QColor(colors["axis"])))
        axis.setTitleBrush(QBrush(QColor(colors["axis"])))
        axis.setLinePenColor(QColor(colors["grid"]))
        axis.setGridLineColor(QColor(colors["grid"]))


def chart_line_color(theme: str) -> QColor:
    return QColor(theme_colors(theme)["line"])


__all__ = [
    "apply_theme",
    "current_theme",
    "theme_is_dark",
    "theme_colors",
    "pnl_color",
    "style_chart",
    "chart_line_color",
    "THEME_LIGHT",
    "THEME_DARK",
]
