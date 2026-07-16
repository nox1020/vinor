from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Workflow states
STATE_INIT = "INIT"
STATE_SEARCHING = "SEARCHING"
STATE_ANALYZING = "ANALYZING"
STATE_READY = "READY"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"

WORKFLOW_STATES = (
    STATE_INIT,
    STATE_SEARCHING,
    STATE_ANALYZING,
    STATE_READY,
    STATE_DONE,
    STATE_FAILED,
)

# Retry strategies (objects only — never prompt text)
STRATEGY_DEFAULT = "default"
STRATEGY_LEAN = "lean"  # skip planning hint/seed on retry prepare


@dataclass
class ConfidenceScore:
    value: float = 1.0  # 0.0–1.0
    reason: str = ""
    signals: dict[str, Any] = field(default_factory=dict)

    def is_low(self, threshold: float = 0.55) -> bool:
        return float(self.value) < float(threshold)


@dataclass
class QualityReport:
    complete: bool = True
    found_suitable: bool = True
    needs_continue: bool = False
    reason: str = ""
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowState:
    state: str = STATE_INIT
    route: str = ""
    strategy: str = STRATEGY_DEFAULT
    retry_count: int = 0
    recovery_count: int = 0
    skipped_steps: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    confidence: ConfidenceScore = field(default_factory=ConfidenceScore)
    quality: QualityReport | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition(self, new_state: str, *, reason: str = "") -> None:
        prev = self.state
        self.state = new_state
        self.history.append(f"{prev}->{new_state}" + (f":{reason}" if reason else ""))


@dataclass
class AdaptiveRequest:
    message: str
    route: str = ""
    audience: str = ""
    voice: str = ""
    chip_intent: str = ""
    user_key: str = ""


@dataclass
class AdaptiveOutcome:
    workflow: WorkflowState
    execution_time_ms: int = 0
    extra_tokens: int = 0  # always 0 — no prompt injection


class WorkflowMachine(Protocol):
    def start(self, *, route: str) -> WorkflowState:
        ...

    def advance(self, wf: WorkflowState, target: str, *, reason: str = "") -> WorkflowState:
        ...


class ConfidenceEstimator(Protocol):
    def estimate_prepare(self, *, route: str, agent_status: str, used_components: list[str]) -> ConfidenceScore:
        ...

    def estimate_response(
        self,
        *,
        route: str,
        reply: str,
        land_codes: list[str],
        ok: bool,
    ) -> ConfidenceScore:
        ...


class QualityEvaluator(Protocol):
    def evaluate(
        self,
        *,
        route: str,
        reply: str,
        land_codes: list[str],
        ok: bool,
        confidence: ConfidenceScore,
    ) -> QualityReport:
        ...


class RetryPolicy(Protocol):
    def should_retry(self, wf: WorkflowState, confidence: ConfidenceScore) -> bool:
        ...

    def next_strategy(self, wf: WorkflowState) -> str:
        ...


class RecoveryPolicy(Protocol):
    def recover(self, wf: WorkflowState, *, error: str = "", quality: QualityReport | None = None) -> WorkflowState:
        ...


class AdaptiveController(Protocol):
    def begin(self, req: AdaptiveRequest) -> AdaptiveOutcome:
        ...

    def after_agent_prepare(
        self,
        wf: WorkflowState,
        *,
        agent_status: str,
        used_components: list[str],
        selected_agent: str,
    ) -> AdaptiveOutcome:
        ...

    def after_response(
        self,
        wf: WorkflowState,
        *,
        reply: str,
        land_codes: list[str],
        ok: bool,
    ) -> AdaptiveOutcome:
        ...

    def on_failure(self, wf: WorkflowState, *, error: str = "") -> AdaptiveOutcome:
        ...
