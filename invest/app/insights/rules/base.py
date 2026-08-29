"""Base protocol for insight rules."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.analytics.models import AnalyticsBundle
from app.insights.models import Insight


class InsightRule(ABC):
    """
    One independent rule with a single responsibility.

    Rules must only read ``AnalyticsBundle`` — never repositories, DB, or UI.
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Stable unique id used in Insight.id / registry."""

    @abstractmethod
    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        """Return zero or more insights for this analytics snapshot."""
