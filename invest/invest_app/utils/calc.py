"""Calculation helpers for portfolio and trades."""

from __future__ import annotations

from datetime import date, datetime


def unrealized_pnl(
    quantity: float,
    buy_price: float,
    current_price: float,
    buy_fee: float = 0.0,
) -> float:
    """Unrealized profit/loss for an open position."""
    return (current_price - buy_price) * quantity - buy_fee


def unrealized_pnl_pct(
    quantity: float,
    buy_price: float,
    current_price: float,
    buy_fee: float = 0.0,
) -> float:
    cost = quantity * buy_price + buy_fee
    if cost == 0:
        return 0.0
    return (unrealized_pnl(quantity, buy_price, current_price, buy_fee) / cost) * 100.0


def realized_pnl(
    quantity: float,
    buy_price: float,
    sell_price: float,
    buy_fee: float = 0.0,
    sell_fee: float = 0.0,
) -> float:
    """Final profit/loss after closing a trade."""
    return (sell_price - buy_price) * quantity - buy_fee - sell_fee


def return_pct(
    quantity: float,
    buy_price: float,
    sell_price: float,
    buy_fee: float = 0.0,
    sell_fee: float = 0.0,
) -> float:
    cost = quantity * buy_price + buy_fee
    if cost == 0:
        return 0.0
    return (realized_pnl(quantity, buy_price, sell_price, buy_fee, sell_fee) / cost) * 100.0


def holding_days(buy_date: str, sell_date: str) -> int:
    """Number of calendar days between buy and sell (ISO date strings)."""
    start = _parse_date(buy_date)
    end = _parse_date(sell_date)
    return max(0, (end - start).days)


def _parse_date(value: str) -> date:
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value[:10])


def portfolio_return_pct(total_value: float, total_cost: float) -> float:
    if total_cost == 0:
        return 0.0
    return ((total_value - total_cost) / total_cost) * 100.0
