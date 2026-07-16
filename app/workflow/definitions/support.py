from __future__ import annotations

from app.conversation.interfaces import INTENT_SUPPORT
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_SUPPORT, StepDefinition, WorkflowSpec


class SupportWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_SUPPORT,
        name="Support Request",
        intent=INTENT_SUPPORT,
        object_type="SupportTicket",
        steps=[
            StepDefinition("topic", "topic", "موضوع پشتیبانی چیست؟", validator="non_empty"),
            StepDefinition("details", "details", "جزئیات مشکل را بنویسید.", validator="non_empty"),
            StepDefinition("confirm", "confirm", "تیکت ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
