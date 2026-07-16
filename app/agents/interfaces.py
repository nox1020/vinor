from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Agent ids
AGENT_PROPERTY_SEARCH = "property_search"
AGENT_PROPERTY_ANALYSIS = "property_analysis"
AGENT_CUSTOMER_MEMORY = "customer_memory"
AGENT_RECOMMENDATION = "recommendation"
AGENT_NEGOTIATION = "negotiation"
AGENT_FOLLOW_UP = "follow_up"

ALL_AGENT_IDS = (
    AGENT_PROPERTY_SEARCH,
    AGENT_PROPERTY_ANALYSIS,
    AGENT_CUSTOMER_MEMORY,
    AGENT_RECOMMENDATION,
    AGENT_NEGOTIATION,
    AGENT_FOLLOW_UP,
)


@dataclass
class AgentContext:
    """Shared request context — no duplicated business payloads."""

    message: str
    route: str = ""
    audience: str = ""
    voice: str = ""
    chip_intent: str = ""
    user_key: str = ""
    thread_id: str | None = None
    context_budget_chars: int = 3000
    shared: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    agent_id: str
    status: str = "ready"  # ready|skeleton|skipped|error
    ok: bool = True
    skipped: bool = False
    used_components: list[str] = field(default_factory=list)
    agent_tokens: int = 0  # extra prompt tokens introduced by agent (target 0)
    execution_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class AgentSelection:
    selected_agent: str = ""
    skipped_agents: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class AgentOutcome:
    selection: AgentSelection
    result: AgentResult | None = None
    execution_time_ms: int = 0


class Agent(Protocol):
    @property
    def agent_id(self) -> str:
        ...

    @property
    def active(self) -> bool:
        ...

    def run(self, ctx: AgentContext) -> AgentResult:
        ...


class AgentRegistry(Protocol):
    def register(self, agent: Agent) -> None:
        ...

    def get(self, agent_id: str) -> Agent | None:
        ...

    def list_ids(self) -> list[str]:
        ...

    def all_agents(self) -> list[Agent]:
        ...


class AgentSelector(Protocol):
    def select(self, *, route: str, ctx: AgentContext) -> AgentSelection:
        ...


class AgentManager(Protocol):
    def prepare(self, ctx: AgentContext) -> AgentOutcome:
        ...
