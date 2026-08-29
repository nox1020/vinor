"""Investment Insights Engine — rule-based, analytics-only."""

from __future__ import annotations

import logging

from app.analytics.models import AnalyticsBundle
from app.insights.models import Insight, InsightBundle
from app.insights.registry import InsightRuleRegistry
from app.utils.dates import now_iso

logger = logging.getLogger(__name__)


class InvestmentInsightsEngine:
    """
    Run registered insight rules against an ``AnalyticsBundle``.

    Never touches repositories, database, or UI.
    """

    def __init__(self, registry: InsightRuleRegistry | None = None) -> None:
        self._registry = registry or InsightRuleRegistry.with_defaults()
        self._cache: InsightBundle | None = None

    @property
    def registry(self) -> InsightRuleRegistry:
        return self._registry

    def invalidate_cache(self) -> None:
        self._cache = None

    def generate(
        self,
        bundle: AnalyticsBundle,
        *,
        use_cache: bool = True,
    ) -> InsightBundle:
        """Evaluate all rules; cache by analytics fingerprint."""
        if (
            use_cache
            and self._cache is not None
            and self._cache.fingerprint == bundle.fingerprint
        ):
            return self._cache

        insights: list[Insight] = []
        for rule in self._registry.all_rules():
            try:
                produced = rule.evaluate(bundle)
            except Exception:
                logger.exception("Insight rule failed: %s", rule.rule_id)
                continue
            insights.extend(produced)

        insights.sort(key=lambda i: i.sort_key())
        result = InsightBundle(
            insights=tuple(insights),
            fingerprint=bundle.fingerprint,
            generated_at=now_iso(),
        )
        if use_cache:
            self._cache = result
        return result
