from __future__ import annotations

from app.workflow.interfaces import WorkflowContext, WorkflowSpec


class BaseWorkflow:
    """Workflow object base — builds structured payload outside Prompt."""

    spec: WorkflowSpec

    def build_object(self, ctx: WorkflowContext) -> dict:
        return {
            "type": self.spec.object_type,
            "workflow_id": self.spec.id,
            "workflow_name": self.spec.name,
            "intent": ctx.intent or self.spec.intent,
            "role": ctx.role,
            "fields": dict(ctx.collected or {}),
            "status": ctx.state,
            "completed_steps": list(ctx.completed_steps or []),
        }
