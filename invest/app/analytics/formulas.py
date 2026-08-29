"""Pure financial formulas for portfolio analytics (no I/O).

See docs/ANALYTICS.md for definitions and limitations.
"""

from __future__ import annotations


def roi(total_pnl: float, invested: float) -> float:
    """Return on investment (%). invested must be > 0 for non-zero denominator."""
    if invested <= 0:
        return 0.0
    return (total_pnl / invested) * 100.0


def profit_factor(gross_profit: float, gross_loss: float) -> float:
    """Sum of wins / abs(sum of losses). Losses should be negative."""
    loss_abs = abs(gross_loss)
    if loss_abs <= 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / loss_abs


def win_rate(wins: int, total_closed: int) -> float:
    if total_closed <= 0:
        return 0.0
    return (wins / total_closed) * 100.0


def loss_rate(losses: int, total_closed: int) -> float:
    if total_closed <= 0:
        return 0.0
    return (losses / total_closed) * 100.0


def expectancy(avg_winner: float, avg_loser: float, win_rate_pct: float) -> float:
    """Expected PnL per closed trade (win rate as 0–100). avg_loser is typically negative."""
    wr = win_rate_pct / 100.0
    lr = 1.0 - wr
    return (avg_winner * wr) + (avg_loser * lr)


def recovery_factor(net_profit: float, max_drawdown: float) -> float:
    """Net profit / max peak-to-trough drawdown (absolute)."""
    if max_drawdown <= 0:
        return float("inf") if net_profit > 0 else 0.0
    return net_profit / max_drawdown


def allocation_pct(part_value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return (part_value / total) * 100.0


def weighted_average(prices: list[float], weights: list[float]) -> float:
    total_w = sum(weights)
    if total_w <= 0:
        return 0.0
    return sum(p * w for p, w in zip(prices, weights, strict=True)) / total_w


def max_drawdown_from_series(values: list[float]) -> float:
    """Peak-to-trough drop on a value series (absolute, not %)."""
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def period_success_rate(wins: int, trades: int) -> float:
    return win_rate(wins, trades)
