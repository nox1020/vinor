from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ExecutivePlan:
    """Which cognitive layers to run — no text, no agents created."""

    run_goals: bool = True
    run_world_model: bool = True
    run_long_plan: bool = True
    run_supervisor: bool = True
    run_agents: bool = True
    run_decision: bool = True
    run_bi: bool = True
    run_reflection: bool = True
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_goals": self.run_goals,
            "run_world_model": self.run_world_model,
            "run_long_plan": self.run_long_plan,
            "run_supervisor": self.run_supervisor,
            "run_agents": self.run_agents,
            "run_decision": self.run_decision,
            "run_bi": self.run_bi,
            "run_reflection": self.run_reflection,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass
class ExecutiveRequest:
    message: str = ""
    audience: str = ""
    intent: str = ""
    conversation_handled: bool = False


class ExecutiveAI(Protocol):
    def plan(self, req: ExecutiveRequest) -> ExecutivePlan:
        ...
