# -*- coding: utf-8 -*-
"""CRM follow-up form workflow — Phase 6 (gated by VINOR_INTEGRATION_WORKFLOWS_ENABLED)."""
from __future__ import annotations

from app.conversation.interfaces import INTENT_FOLLOWUP
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_CRM_FOLLOWUP, StepDefinition, WorkflowSpec


class CrmFollowupWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_CRM_FOLLOWUP,
        name="CRM Follow-up",
        intent=INTENT_FOLLOWUP,
        object_type="FollowupRequest",
        steps=[
            StepDefinition("customer_phone", "customer_phone", "شماره مشتری؟", validator="phone"),
            StepDefinition("notes", "notes", "یادداشت پیگیری؟", validator="non_empty"),
            StepDefinition("due_at", "due_at", "موعد؟ (مثلاً فردا یا تاریخ)", validator="non_empty"),
            StepDefinition("confirm", "confirm", "پیگیری ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
