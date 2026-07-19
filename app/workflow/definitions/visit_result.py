# -*- coding: utf-8 -*-
"""Visit result form workflow — Phase 6 (gated by VINOR_INTEGRATION_WORKFLOWS_ENABLED)."""
from __future__ import annotations

from app.conversation.interfaces import INTENT_VISIT_RESULT
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_VISIT_RESULT, StepDefinition, WorkflowSpec


class VisitResultWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_VISIT_RESULT,
        name="Visit Result",
        intent=INTENT_VISIT_RESULT,
        object_type="VisitResultRequest",
        steps=[
            StepDefinition("land_code", "land_code", "", validator="land_code"),
            StepDefinition(
                "outcome",
                "outcome",
                "نتیجه بازدید؟ (interested / not_interested / follow_up / no_show)",
                validator="non_empty",
            ),
            StepDefinition("notes", "notes", "یادداشت؟ (یا بنویس رد)", validator="non_empty"),
            StepDefinition("confirm", "confirm", "نتیجه ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
