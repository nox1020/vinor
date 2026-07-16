from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CustomerSuccessPlan:
    """Post-interaction lifecycle plan — no follow-up dialogue text."""

    customer_stage: str = "aware"  # aware|interested|evaluating|negotiating|ready|won|dormant
    next_action: str = "nurture"
    followup_type: str = "check_in"  # check_in|visit_reminder|offer_follow|deal_push|reactivate
    followup_time: str = "2d"  # relative: 1h|4h|1d|2d|3d|7d
    priority: str = "medium"  # low|medium|high
    conversion_probability: float = 0.0
    urgency: str = "normal"  # low|normal|high
    reason: str = ""
    confidence: float = 0.0
    compact_hint: str = ""
    customer_success_tokens: int = 0
    build_time_ms: int = 0
    cache_hit: bool = False
    reuse_analysis: bool = False
    reuse_recommendation: bool = False
    reuse_negotiation: bool = False
    reuse_customer_profile: bool = False
    reuse_workflow: bool = False
    reuse_planning: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_stage": self.customer_stage,
            "next_action": self.next_action,
            "followup_type": self.followup_type,
            "followup_time": self.followup_time,
            "priority": self.priority,
            "conversion_probability": self.conversion_probability,
            "urgency": self.urgency,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass
class CustomerSuccessRequest:
    message: str = ""
    route: str = ""
    audience: str = ""
    user_key: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    context_budget_chars: int = 55


class ConversionAnalyzer(Protocol):
    def analyze(
        self,
        *,
        profile: dict[str, Any],
        negotiation: dict[str, Any],
        recommendation: dict[str, Any],
        workflow: dict[str, Any],
        shared: dict[str, Any],
    ) -> tuple[float, str]:
        """Returns (conversion_probability, customer_stage)."""
        ...


class NextActionBuilder(Protocol):
    def build(
        self,
        *,
        stage: str,
        conversion_probability: float,
        negotiation: dict[str, Any],
        profile: dict[str, Any],
        workflow: dict[str, Any],
    ) -> tuple[str, str, str, str, str]:
        """Returns (next_action, followup_type, followup_time, priority, urgency)."""
        ...


class FollowUpPlanner(Protocol):
    def plan(self, req: CustomerSuccessRequest) -> CustomerSuccessPlan:
        ...


class CustomerSuccessCache(Protocol):
    def get(self, key: str) -> CustomerSuccessPlan | None:
        ...

    def put(self, key: str, plan: CustomerSuccessPlan) -> None:
        ...


class CustomerSuccessManager(Protocol):
    def run(self, req: CustomerSuccessRequest) -> CustomerSuccessPlan:
        ...
