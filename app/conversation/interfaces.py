from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Roles
ROLE_GUEST = "guest"
ROLE_USER = "user"
ROLE_PARTNER = "partner"
ROLE_PREMIUM = "premium_partner"

# Intents
INTENT_SEARCH = "search_property"
INTENT_REGISTER_PROPERTY = "register_property"
INTENT_EDIT_PROPERTY = "edit_property"
INTENT_BECOME_PARTNER = "become_partner"
INTENT_COMPARE = "compare"
INTENT_RECOMMENDATION = "recommendation"
INTENT_NEGOTIATION = "negotiation"
INTENT_VISIT = "visit"
INTENT_DEAL = "deal"
INTENT_OFFER = "offer"
INTENT_VISIT_RESULT = "visit_result"
INTENT_FOLLOWUP = "followup"
INTENT_CONTRACT = "contract"
INTENT_SUPPORT = "support"
INTENT_GENERAL = "general_chat"

# Workflow ids
WF_PROPERTY_REGISTRATION = "property_registration"
WF_PROPERTY_EDITING = "property_editing"
WF_PARTNER_ONBOARDING = "partner_onboarding"
WF_VISIT = "visit"
WF_DEAL = "deal"
WF_SUPPORT = "support"
WF_GENERAL = "general_conversation"
WF_NONE = "none"

# Conversation / Workflow states (Phase 12 extended)
STATE_START = "START"
STATE_INIT = "INIT"
STATE_COLLECTING = "COLLECTING"
STATE_VALIDATING = "VALIDATING"
STATE_WAITING = "WAITING"
STATE_WAITING_USER = "WAITING_USER"
STATE_READY = "READY"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"
STATE_CANCELLED = "CANCELLED"


@dataclass
class IdentityInfo:
    role: str = ROLE_GUEST
    user_key: str = ""
    phone: str = ""
    is_logged_in: bool = False
    is_partner: bool = False
    is_premium: bool = False
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntentInfo:
    intent: str = INTENT_GENERAL
    confidence: float = 0.5
    reason: str = ""


@dataclass
class WorkflowStep:
    id: str
    field: str
    question: str
    required: bool = True


@dataclass
class WorkflowDefinition:
    id: str
    intent: str
    object_type: str
    steps: list[WorkflowStep] = field(default_factory=list)


@dataclass
class ConversationSession:
    session_id: str
    user_key: str = ""
    role: str = ROLE_GUEST
    intent: str = INTENT_GENERAL
    workflow_id: str = WF_NONE
    state: str = STATE_START
    current_step: str = ""
    collected: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    object_type: str = ""
    workflow_name: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationOutcome:
    handled: bool = False
    ok: bool = True
    reply: str = ""
    session: ConversationSession | None = None
    structured_object: dict[str, Any] | None = None
    pass_to_supervisor: bool = True
    extra_tokens: int = 0
    observability: dict[str, Any] = field(default_factory=dict)


class IdentityResolver(Protocol):
    def resolve(self, *, user_key: str, audience: str, phone: str = "") -> IdentityInfo:
        ...


class RoleResolver(Protocol):
    def resolve(self, identity: IdentityInfo) -> str:
        ...


class IntentResolver(Protocol):
    def resolve(self, *, message: str, chip_intent: str = "") -> IntentInfo:
        ...


class WorkflowResolver(Protocol):
    def resolve(self, intent: str) -> str:
        ...

    def definition(self, workflow_id: str) -> WorkflowDefinition | None:
        ...


class SessionStore(Protocol):
    def load(self, user_key: str) -> ConversationSession | None:
        ...

    def save(self, session: ConversationSession) -> None:
        ...

    def clear(self, user_key: str) -> None:
        ...


class ConversationManager(Protocol):
    def handle(
        self,
        *,
        message: str,
        user_key: str,
        audience: str,
        voice: str = "",
        chip_intent: str = "",
        thread_id: str | None = None,
    ) -> ConversationOutcome:
        ...
