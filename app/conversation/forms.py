from __future__ import annotations

"""Legacy form definitions — Phase 12: sourced from Workflow Engine registry."""

from app.conversation.interfaces import WorkflowDefinition, WorkflowStep
from app.workflow.registry import WorkflowRegistry


def _load_forms() -> dict[str, WorkflowDefinition]:
    forms: dict[str, WorkflowDefinition] = {}
    for spec in WorkflowRegistry().all_specs():
        if spec.pass_through:
            continue
        forms[spec.id] = WorkflowDefinition(
            id=spec.id,
            intent=spec.intent,
            object_type=spec.object_type,
            steps=[
                WorkflowStep(s.id, s.field, s.question, s.required)
                for s in spec.steps
            ],
        )
    return forms


FORMS: dict[str, WorkflowDefinition] = _load_forms()


def form_for_intent(intent: str) -> WorkflowDefinition | None:
    for wf in FORMS.values():
        if wf.intent == intent:
            return wf
    return None
