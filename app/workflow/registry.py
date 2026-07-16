from __future__ import annotations

from app.conversation.interfaces import (
    INTENT_BECOME_PARTNER,
    INTENT_COMPARE,
    INTENT_DEAL,
    INTENT_EDIT_PROPERTY,
    INTENT_GENERAL,
    INTENT_NEGOTIATION,
    INTENT_RECOMMENDATION,
    INTENT_REGISTER_PROPERTY,
    INTENT_SEARCH,
    INTENT_SUPPORT,
    INTENT_VISIT,
)
from app.workflow.definitions import ALL_WORKFLOWS
from app.workflow.interfaces import (
    WF_NONE,
    WorkflowObject,
    WorkflowSpec,
)

# Search/compare/recommend/negotiation stay Supervisor-owned (not form workflows).
_PASS_THROUGH_INTENTS = frozenset(
    {
        INTENT_SEARCH,
        INTENT_COMPARE,
        INTENT_RECOMMENDATION,
        INTENT_NEGOTIATION,
    }
)


class WorkflowRegistry:
    def __init__(self, workflows: list[WorkflowObject] | None = None):
        self._by_id: dict[str, WorkflowObject] = {}
        self._by_intent: dict[str, str] = {}
        for wf in workflows or ALL_WORKFLOWS:
            self.register(wf)

    def register(self, wf: WorkflowObject) -> None:
        self._by_id[wf.spec.id] = wf
        self._by_intent[wf.spec.intent] = wf.spec.id

    def get(self, workflow_id: str) -> WorkflowObject | None:
        return self._by_id.get(workflow_id)

    def get_spec(self, workflow_id: str) -> WorkflowSpec | None:
        wf = self.get(workflow_id)
        return wf.spec if wf else None

    def resolve_id(self, intent: str) -> str:
        intent = (intent or "").strip()
        if intent in _PASS_THROUGH_INTENTS:
            return WF_NONE
        if intent == INTENT_GENERAL:
            return self._by_intent.get(INTENT_GENERAL, WF_NONE)
        return self._by_intent.get(intent, WF_NONE)

    def all_specs(self) -> list[WorkflowSpec]:
        return [wf.spec for wf in self._by_id.values()]
