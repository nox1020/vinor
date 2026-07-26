from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Workflow / route ids
ROUTE_PROPERTY_SEARCH = "property_search"
ROUTE_PROPERTY_COMPARE = "property_compare"
ROUTE_FAQ = "faq"
ROUTE_FOLLOW_UP = "follow_up"
ROUTE_GENERAL_CHAT = "general_chat"
ROUTE_GREETING = "greeting"
ROUTE_PARTNER_OPS = "partner_ops"  # visit/deal/listing chip flows


@dataclass(frozen=True)
class ComponentFlags:
    use_planning: bool = False
    use_memory: bool = False
    use_rag: bool = False
    use_tools: bool = True
    use_llm: bool = True
    inject_planning_hint: bool = False
    seed_planning_tools: bool = False
    context_budget_chars: int = 2400


@dataclass
class Workflow:
    route: str
    flags: ComponentFlags
    reason: str = ""
    executed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SupervisorRequest:
    message: str
    audience: str = ""
    voice: str = ""
    chip_intent: str = ""
    user_key: str = ""


@dataclass
class SupervisorOutcome:
    workflow: Workflow
    routing_time_ms: int = 0


class Router(Protocol):
    def route(self, req: SupervisorRequest) -> str:
        ...


class ExecutionPolicy(Protocol):
    def resolve(self, route: str, *, req: SupervisorRequest) -> ComponentFlags:
        ...


class Supervisor(Protocol):
    def decide(self, req: SupervisorRequest) -> SupervisorOutcome:
        ...


class SupervisorManager(Protocol):
    def orchestrate(self, req: SupervisorRequest) -> SupervisorOutcome:
        ...
