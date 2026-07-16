from __future__ import annotations

from app.adaptive.config import confidence_low_threshold, max_retries
from app.adaptive.interfaces import (
    STRATEGY_DEFAULT,
    STRATEGY_LEAN,
    ConfidenceScore,
    RetryPolicy,
    WorkflowState,
)
from app.supervisor.interfaces import ROUTE_PROPERTY_COMPARE, ROUTE_PROPERTY_SEARCH


class RuleRetryPolicy(RetryPolicy):
    """At most one retry with alternate strategy — no LLM, no prompt growth."""

    def should_retry(self, wf: WorkflowState, confidence: ConfidenceScore) -> bool:
        if wf.retry_count >= max_retries():
            return False
        if wf.route not in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            return False
        # Only retry at prepare phase while still searching/analyzing
        if wf.state not in ("INIT", "SEARCHING", "ANALYZING"):
            return False
        return confidence.is_low(confidence_low_threshold())

    def next_strategy(self, wf: WorkflowState) -> str:
        if wf.strategy == STRATEGY_DEFAULT:
            return STRATEGY_LEAN
        return STRATEGY_DEFAULT
