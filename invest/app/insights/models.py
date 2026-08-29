"""Insight domain models (UI-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.insights.categories import InsightCategory
from app.insights.severity import InsightSeverity


@dataclass(frozen=True)
class Insight:
    """A single actionable investment insight produced by a rule."""

    id: str
    title: str
    description: str
    summary: str
    category: InsightCategory
    severity: InsightSeverity
    priority: int
    action: str
    related_assets: tuple[str, ...] = ()
    related_trades: tuple[int, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    rule_id: str = ""

    def sort_key(self) -> tuple[int, int, str]:
        """Severity desc, then priority desc, then id."""
        return (-int(self.severity), -self.priority, self.id)


@dataclass(frozen=True)
class InsightBundle:
    """Cached set of insights for one analytics fingerprint."""

    insights: tuple[Insight, ...]
    fingerprint: str
    generated_at: str

    @property
    def count(self) -> int:
        return len(self.insights)


@dataclass(frozen=True)
class InsightViewModel:
    """Display-ready insight row for UI binding (no business logic)."""

    id: str
    title: str
    summary: str
    description: str
    action: str
    category: str
    severity: str
    severity_level: int
    priority: int
    related_assets: tuple[str, ...]
    metrics_text: str
    created_at: str
