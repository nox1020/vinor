from __future__ import annotations

from app.conversation.interfaces import INTENT_GENERAL
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_GENERAL, WorkflowSpec


class GeneralConversationWorkflow(BaseWorkflow):
    """Pass-through workflow — no form steps; Supervisor/Agents handle chat."""

    spec = WorkflowSpec(
        id=WF_GENERAL,
        name="General Conversation",
        intent=INTENT_GENERAL,
        object_type="GeneralConversation",
        steps=[],
        pass_through=True,
    )
