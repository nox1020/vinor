from __future__ import annotations

import time

from app.agents.interfaces import (
    AGENT_CUSTOMER_MEMORY,
    AGENT_FOLLOW_UP,
    AGENT_NEGOTIATION,
    AGENT_PROPERTY_ANALYSIS,
    AGENT_RECOMMENDATION,
    Agent,
    AgentContext,
    AgentResult,
)


class SkeletonAgent(Agent):
    """Placeholder for future phases — registered but never executed as active."""

    def __init__(self, agent_id: str, *, label: str = ""):
        self._id = agent_id
        self._label = label or agent_id

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def active(self) -> bool:
        return False

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        return AgentResult(
            agent_id=self.agent_id,
            status="skeleton",
            ok=True,
            skipped=True,
            used_components=[],
            agent_tokens=0,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={"phase": "future", "label": self._label},
        )


def make_skeleton_agents() -> list[Agent]:
    return [
        SkeletonAgent(AGENT_PROPERTY_ANALYSIS, label="Property Analysis Agent"),
        SkeletonAgent(AGENT_CUSTOMER_MEMORY, label="Customer Memory Agent"),
        SkeletonAgent(AGENT_RECOMMENDATION, label="Recommendation Agent"),
        SkeletonAgent(AGENT_NEGOTIATION, label="Negotiation Agent"),
        SkeletonAgent(AGENT_FOLLOW_UP, label="Follow-up Agent"),
    ]
