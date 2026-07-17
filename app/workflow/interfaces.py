from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Workflow states (Phase 12) — outside Prompt
WF_STATE_INIT = "INIT"
WF_STATE_COLLECTING = "COLLECTING"
WF_STATE_VALIDATING = "VALIDATING"
WF_STATE_WAITING_USER = "WAITING_USER"
WF_STATE_READY = "READY"
WF_STATE_COMPLETED = "COMPLETED"
WF_STATE_FAILED = "FAILED"
WF_STATE_CANCELLED = "CANCELLED"

# Workflow ids
WF_PROPERTY_REGISTRATION = "property_registration"
WF_PROPERTY_EDITING = "property_editing"
WF_PARTNER_ONBOARDING = "partner_onboarding"
WF_VISIT = "visit"
WF_DEAL = "deal"
WF_OFFER = "offer"
WF_VISIT_RESULT = "visit_result"
WF_CRM_FOLLOWUP = "crm_followup"
WF_CLOSING_CONTRACT = "closing_contract"
WF_SUPPORT = "support"
WF_GENERAL = "general_conversation"
WF_NONE = "none"

ACTIVE_STATES = frozenset(
    {
        WF_STATE_INIT,
        WF_STATE_COLLECTING,
        WF_STATE_VALIDATING,
        WF_STATE_WAITING_USER,
        WF_STATE_READY,
    }
)

TERMINAL_STATES = frozenset(
    {WF_STATE_COMPLETED, WF_STATE_FAILED, WF_STATE_CANCELLED}
)


@dataclass
class StepDefinition:
    id: str
    field: str
    question: str
    required: bool = True
    validator: str = "non_empty"  # key into validation registry


@dataclass
class WorkflowSpec:
    id: str
    name: str
    intent: str
    object_type: str
    steps: list[StepDefinition] = field(default_factory=list)
    pass_through: bool = False  # General / search-like → Supervisor


@dataclass
class ValidationResult:
    ok: bool = True
    error: str = ""
    normalized: Any = None


@dataclass
class WorkflowContext:
    workflow_id: str = WF_NONE
    workflow_name: str = ""
    state: str = WF_STATE_INIT
    current_step: str = ""
    collected: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    validation_ok: bool = True
    role: str = ""
    intent: str = ""
    object_type: str = ""
    user_key: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "state": self.state,
            "current_step": self.current_step,
            "collected": dict(self.collected or {}),
            "missing": list(self.missing or []),
            "completed_steps": list(self.completed_steps or []),
            "validation_errors": list(self.validation_errors or []),
            "validation_ok": bool(self.validation_ok),
            "role": self.role,
            "intent": self.intent,
            "object_type": self.object_type,
            "user_key": self.user_key,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "WorkflowContext":
        d = d or {}
        return cls(
            workflow_id=str(d.get("workflow_id") or WF_NONE),
            workflow_name=str(d.get("workflow_name") or ""),
            state=str(d.get("state") or WF_STATE_INIT),
            current_step=str(d.get("current_step") or ""),
            collected=dict(d.get("collected") or {}),
            missing=list(d.get("missing") or []),
            completed_steps=list(d.get("completed_steps") or []),
            validation_errors=list(d.get("validation_errors") or []),
            validation_ok=bool(d.get("validation_ok", True)),
            role=str(d.get("role") or ""),
            intent=str(d.get("intent") or ""),
            object_type=str(d.get("object_type") or ""),
            user_key=str(d.get("user_key") or ""),
            started_at=float(d.get("started_at") or 0),
            updated_at=float(d.get("updated_at") or 0),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class WorkflowEngineResult:
    handled: bool = False
    ok: bool = True
    reply: str = ""
    context: WorkflowContext | None = None
    structured_object: dict[str, Any] | None = None
    pass_to_supervisor: bool = True
    next_action: str = ""  # ask_user | complete | cancel | pass_supervisor | fail
    extra_tokens: int = 0
    observability: dict[str, Any] = field(default_factory=dict)


class WorkflowObject(Protocol):
    spec: WorkflowSpec

    def build_object(self, ctx: WorkflowContext) -> dict[str, Any]:
        ...


class WorkflowEngine(Protocol):
    def start(
        self,
        *,
        workflow_id: str,
        user_key: str,
        role: str,
        intent: str,
        message: str = "",
    ) -> WorkflowEngineResult:
        ...

    def continue_(
        self,
        *,
        ctx: WorkflowContext,
        message: str,
    ) -> WorkflowEngineResult:
        ...

    def cancel(self, *, ctx: WorkflowContext) -> WorkflowEngineResult:
        ...

    def resolve_id(self, intent: str) -> str:
        ...

    def get_spec(self, workflow_id: str) -> WorkflowSpec | None:
        ...
