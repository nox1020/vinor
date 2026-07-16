from __future__ import annotations

import time

from app.adaptive.interfaces import (
    STATE_ANALYZING,
    STATE_DONE,
    STATE_FAILED,
    STATE_READY,
    STATE_SEARCHING,
    AdaptiveController,
    AdaptiveOutcome,
    AdaptiveRequest,
    ConfidenceEstimator,
    QualityEvaluator,
    RecoveryPolicy,
    RetryPolicy,
    STRATEGY_LEAN,
    WorkflowMachine,
    WorkflowState,
)
from app.supervisor.interfaces import ROUTE_PROPERTY_COMPARE, ROUTE_PROPERTY_SEARCH


class DefaultAdaptiveController(AdaptiveController):
    def __init__(
        self,
        *,
        machine: WorkflowMachine,
        confidence: ConfidenceEstimator,
        evaluator: QualityEvaluator,
        retry: RetryPolicy,
        recovery: RecoveryPolicy,
    ):
        self._machine = machine
        self._confidence = confidence
        self._evaluator = evaluator
        self._retry = retry
        self._recovery = recovery

    def begin(self, req: AdaptiveRequest) -> AdaptiveOutcome:
        t0 = time.perf_counter()
        wf = self._machine.start(route=req.route)
        route = req.route or ""
        if route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            self._machine.advance(wf, STATE_SEARCHING, reason="search_route")
        elif route:
            self._machine.advance(wf, STATE_ANALYZING, reason="light_route")
        else:
            self._machine.advance(wf, STATE_READY, reason="no_route")
        return AdaptiveOutcome(
            workflow=wf,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            extra_tokens=0,
        )

    def after_agent_prepare(
        self,
        wf: WorkflowState,
        *,
        agent_status: str,
        used_components: list[str],
        selected_agent: str,
    ) -> AdaptiveOutcome:
        t0 = time.perf_counter()
        conf = self._confidence.estimate_prepare(
            route=wf.route,
            agent_status=agent_status,
            used_components=used_components,
        )
        wf.confidence = conf
        wf.metadata["selected_agent"] = selected_agent or ""

        if self._retry.should_retry(wf, conf):
            wf.retry_count += 1
            wf.strategy = self._retry.next_strategy(wf)
            wf.metadata["retry_strategy"] = wf.strategy
            # Stay in SEARCHING/ANALYZING — alternate strategy applied by caller flags
            if wf.state == STATE_SEARCHING:
                self._machine.advance(wf, STATE_ANALYZING, reason="retry_lean")
            return AdaptiveOutcome(
                workflow=wf,
                execution_time_ms=int((time.perf_counter() - t0) * 1000),
                extra_tokens=0,
            )

        if wf.route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            if wf.state == STATE_SEARCHING:
                self._machine.advance(wf, STATE_ANALYZING, reason="prepare_ok")
            self._machine.advance(wf, STATE_READY, reason="pipeline_ready")
        else:
            self._machine.advance(wf, STATE_READY, reason="passthrough_ready")

        return AdaptiveOutcome(
            workflow=wf,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            extra_tokens=0,
        )

    def after_response(
        self,
        wf: WorkflowState,
        *,
        reply: str,
        land_codes: list[str],
        ok: bool,
    ) -> AdaptiveOutcome:
        t0 = time.perf_counter()
        conf = self._confidence.estimate_response(
            route=wf.route,
            reply=reply or "",
            land_codes=list(land_codes or []),
            ok=ok,
        )
        wf.confidence = conf
        quality = self._evaluator.evaluate(
            route=wf.route,
            reply=reply or "",
            land_codes=list(land_codes or []),
            ok=ok,
            confidence=conf,
        )
        wf.quality = quality

        if not ok:
            self._recovery.recover(wf, error="response_failed", quality=quality)
        elif quality.complete and quality.found_suitable:
            if wf.state in (STATE_SEARCHING, STATE_ANALYZING, "INIT"):
                self._machine.advance(wf, STATE_READY, reason="response_ok")
            if wf.state == STATE_READY:
                self._machine.advance(wf, STATE_DONE, reason="quality_complete")
            elif wf.state != STATE_DONE:
                self._machine.advance(wf, STATE_DONE, reason="quality_complete")
        else:
            self._recovery.recover(wf, quality=quality)

        return AdaptiveOutcome(
            workflow=wf,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            extra_tokens=0,
        )

    def on_failure(self, wf: WorkflowState, *, error: str = "") -> AdaptiveOutcome:
        t0 = time.perf_counter()
        self._recovery.recover(wf, error=error or "failure")
        if wf.state not in (STATE_FAILED, STATE_DONE):
            self._machine.advance(wf, STATE_FAILED, reason=error or "failure")
        return AdaptiveOutcome(
            workflow=wf,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            extra_tokens=0,
        )

    @staticmethod
    def lean_strategy(wf: WorkflowState | None) -> bool:
        return bool(wf and wf.strategy == STRATEGY_LEAN)
