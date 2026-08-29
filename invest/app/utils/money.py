"""Money formatting helpers."""

from __future__ import annotations

from app.config import (
    CURRENCY_LABELS,
    CURRENCY_RIAL,
    CURRENCY_TOMAN,
    CURRENCY_USD,
    CURRENCY_USDT,
)


def format_number(value: float, decimals: int = 0) -> str:
    """Format a number with thousand separators (Persian-friendly Western digits)."""
    if decimals <= 0:
        return f"{int(round(value)):,}"
    return f"{value:,.{decimals}f}"


def to_display_amount(
    value_toman: float,
    currency: str,
    *,
    fx_rate: float | None = None,
) -> float:
    """Convert a toman-based stored value to the selected display currency."""
    if currency == CURRENCY_RIAL:
        return value_toman * 10.0
    if currency in (CURRENCY_USD, CURRENCY_USDT):
        if fx_rate and fx_rate > 0:
            return value_toman / fx_rate
        return value_toman
    return value_toman


def format_money(
    value: float,
    currency: str = CURRENCY_TOMAN,
    *,
    show_sign: bool = False,
    decimals: int | None = None,
    fx_rate: float | None = None,
    convert: bool = True,
) -> str:
    """Format a monetary value with currency label.

    Stored amounts are treated as toman. When ``convert`` is True and currency
    is usd/usdt, ``fx_rate`` (USDT price in toman) is used for conversion.
    Without a rate, amounts stay in toman to avoid a wrong دلار label.
    """
    display_currency = currency
    amount = value
    if convert:
        if currency in (CURRENCY_USD, CURRENCY_USDT) and not (fx_rate and fx_rate > 0):
            display_currency = CURRENCY_TOMAN
            amount = value
        else:
            amount = to_display_amount(value, currency, fx_rate=fx_rate)

    if decimals is None:
        decimals = 2 if display_currency in (CURRENCY_USD, CURRENCY_USDT) else 0
    sign = ""
    if show_sign and amount > 0:
        sign = "+"
    elif amount < 0:
        sign = "-"
        amount = abs(amount)
    label = CURRENCY_LABELS.get(display_currency, display_currency)
    return f"{sign}{format_number(amount, decimals)} {label}"


def format_pct(value: float, *, show_sign: bool = True, decimals: int = 2) -> str:
    sign = ""
    if show_sign and value > 0:
        sign = "+"
    elif value < 0:
        sign = "-"
        value = abs(value)
    return f"{sign}{value:.{decimals}f}%"


def format_qty(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return format_number(value, 0)
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text
