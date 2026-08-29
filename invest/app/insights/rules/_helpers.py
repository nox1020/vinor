"""Shared helpers for insight rule implementations."""

from __future__ import annotations

from typing import Any

from app.insights.categories import InsightCategory
from app.insights.models import Insight
from app.insights.severity import InsightSeverity
from app.utils.dates import now_iso


def make_insight(
    *,
    rule_id: str,
    title: str,
    description: str,
    summary: str,
    category: InsightCategory,
    severity: InsightSeverity,
    action: str,
    priority: int = 50,
    related_assets: list[str] | tuple[str, ...] | None = None,
    related_trades: list[int] | tuple[int, ...] | None = None,
    metrics: dict[str, Any] | None = None,
    suffix: str = "",
) -> Insight:
    """Build a frozen Insight with stable id and timestamp."""
    insight_id = f"{rule_id}{suffix}"
    return Insight(
        id=insight_id,
        title=title,
        description=description,
        summary=summary,
        category=category,
        severity=severity,
        priority=priority,
        action=action,
        related_assets=tuple(related_assets or ()),
        related_trades=tuple(related_trades or ()),
        metrics=dict(metrics or {}),
        created_at=now_iso(),
        rule_id=rule_id,
    )


def pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}%"
