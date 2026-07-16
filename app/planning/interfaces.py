from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


PLAN_PROPERTY_SEARCH = "property_search"
PLAN_PROPERTY_COMPARE = "property_compare"
PLAN_PROPERTY_RECOMMENDATION = "property_recommendation"
PLAN_FOLLOW_UP = "follow_up"
PLAN_INFORMATION = "information"

PLAN_TYPES = (
    PLAN_PROPERTY_SEARCH,
    PLAN_PROPERTY_COMPARE,
    PLAN_PROPERTY_RECOMMENDATION,
    PLAN_FOLLOW_UP,
    PLAN_INFORMATION,
)


@dataclass
class Task:
    id: str
    name: str
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending|running|done|skipped|failed
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    id: str
    plan_type: str
    goal: str
    tasks: list[Task] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    task_id: str
    ok: bool
    tool_name: str = ""
    model_result: dict[str, Any] = field(default_factory=dict)
    ui_action: dict[str, Any] | None = None
    land_codes: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class EvaluationResult:
    goal_met: bool
    sufficient: bool
    needs_more: bool
    reason: str = ""


@dataclass
class PlanningOutcome:
    plan: Plan | None
    executed: list[TaskResult] = field(default_factory=list)
    evaluation: EvaluationResult | None = None
    land_codes: list[str] = field(default_factory=list)
    agent_actions: list[dict[str, Any]] = field(default_factory=list)
    seed_messages: list[dict[str, Any]] = field(default_factory=list)
    compact_hint: str = ""
    planning_time_ms: int = 0
    tasks_count: int = 0
    executed_tasks: int = 0
    planning_tokens: int = 0  # always 0 for rule planner
    execution_tokens: int = 0  # estimated from tool payloads


@dataclass(frozen=True)
class PlanningRequest:
    goal: str
    user_key: str = ""
    audience: str = ""
    voice: str = ""
    thread_id: str | None = None
    chip_intent: str = ""


class Planner(Protocol):
    def create_plan(self, req: PlanningRequest) -> Plan:
        ...


class Executor(Protocol):
    def execute_task(self, task: Task, *, req: PlanningRequest) -> TaskResult:
        ...


class Evaluator(Protocol):
    def evaluate(self, plan: Plan, results: list[TaskResult], *, req: PlanningRequest) -> EvaluationResult:
        ...


class PlanningManager(Protocol):
    def run_once(self, req: PlanningRequest) -> PlanningOutcome:
        ...
