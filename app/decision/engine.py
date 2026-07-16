from __future__ import annotations

import time
from typing import Any

from app.decision.builder import RuleDecisionBuilder
from app.decision.config import load_decision_config
from app.decision.conflict import RuleConflictResolver
from app.decision.interfaces import (
    ConflictResolver,
    DecisionBuilder,
    DecisionEngine,
    DecisionRequest,
    DecisionResult,
    DecisionScorer,
)
from app.decision.scorer import RuleDecisionScorer


class RuleDecisionEngine(DecisionEngine):
    """Final pre-LLM decision — rule-based merge/score/resolve only."""

    def __init__(
        self,
        *,
        scorer: DecisionScorer | None = None,
        resolver: ConflictResolver | None = None,
        builder: DecisionBuilder | None = None,
    ):
        self._scorer = scorer or RuleDecisionScorer()
        self._resolver = resolver or RuleConflictResolver()
        self._builder = builder or RuleDecisionBuilder()

    def decide(self, req: DecisionRequest) -> DecisionResult:
        t0 = time.perf_counter()
        config = (req.config or load_decision_config()).normalized()
        shared = dict(req.shared or {})
        if req.parallel_merge and isinstance(req.parallel_merge, dict):
            shared.setdefault("parallel_merge", req.parallel_merge)
            # Promote nested objects from merge if missing
            for key in (
                "recommendation_items",
                "customer_profile",
                "negotiation_plan",
                "customer_success",
                "analysis_categories",
            ):
                if key not in shared and key in req.parallel_merge:
                    shared[key] = req.parallel_merge[key]
            if not shared.get("recommended_code") and req.parallel_merge.get("recommendation"):
                shared["recommended_code"] = req.parallel_merge.get("recommendation")

        ranked = self._scorer.score_candidates(shared=shared, config=config)
        winner, alts, conflicts, _ccount = self._resolver.resolve(
            ranked=ranked, shared=shared, config=config
        )
        result = self._builder.build(
            winner=winner,
            alternatives=alts,
            conflicts=conflicts,
            shared=shared,
            config=config,
        )
        result.decision_time_ms = int((time.perf_counter() - t0) * 1000)
        return result
