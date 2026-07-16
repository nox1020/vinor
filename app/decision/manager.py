from __future__ import annotations

import time

from app.decision.config import load_decision_config
from app.decision.engine import RuleDecisionEngine
from app.decision.interfaces import DecisionEngine, DecisionManager, DecisionRequest, DecisionResult


class DefaultDecisionManager(DecisionManager):
    def __init__(self, *, engine: DecisionEngine | None = None):
        self._engine = engine or RuleDecisionEngine()

    def run(self, req: DecisionRequest) -> DecisionResult:
        t0 = time.perf_counter()
        if req.config is None:
            req = DecisionRequest(
                message=req.message,
                route=req.route,
                shared=req.shared,
                parallel_merge=req.parallel_merge,
                config=load_decision_config(),
            )
        result = self._engine.decide(req)
        if not result.decision_time_ms:
            result.decision_time_ms = int((time.perf_counter() - t0) * 1000)
        return result
