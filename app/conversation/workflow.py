from __future__ import annotations

from app.conversation.forms import FORMS
from app.conversation.interfaces import WF_NONE, WorkflowDefinition, WorkflowResolver
from app.workflow.config import workflow_engine_enabled
from app.workflow.di import make_workflow_engine


class RuleWorkflowResolver(WorkflowResolver):
    """Selects workflow id; execution is delegated to Workflow Engine (Phase 12)."""

    def __init__(self):
        self._engine = make_workflow_engine() if workflow_engine_enabled() else None

    def resolve(self, intent: str) -> str:
        if self._engine is not None:
            return self._engine.resolve_id(intent)
        from app.conversation.forms import form_for_intent

        form = form_for_intent(intent)
        return form.id if form else WF_NONE

    def definition(self, workflow_id: str) -> WorkflowDefinition | None:
        if self._engine is not None:
            spec = self._engine.get_spec(workflow_id)
            if spec is None or spec.pass_through:
                return None
            from app.conversation.interfaces import WorkflowStep

            return WorkflowDefinition(
                id=spec.id,
                intent=spec.intent,
                object_type=spec.object_type,
                steps=[
                    WorkflowStep(s.id, s.field, s.question, s.required)
                    for s in spec.steps
                ],
            )
        return FORMS.get(workflow_id)
