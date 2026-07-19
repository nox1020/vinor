# -*- coding: utf-8 -*-
"""Closing contract form workflow — Phase 6 (gated by VINOR_INTEGRATION_WORKFLOWS_ENABLED)."""
from __future__ import annotations

from app.conversation.interfaces import INTENT_CONTRACT
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_CLOSING_CONTRACT, StepDefinition, WorkflowSpec


class ClosingContractWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_CLOSING_CONTRACT,
        name="Closing Contract",
        intent=INTENT_CONTRACT,
        object_type="ContractRequest",
        steps=[
            StepDefinition("land_code", "land_code", "", validator="land_code"),
            StepDefinition("title", "title", "عنوان قرارداد؟", validator="non_empty"),
            StepDefinition("document_ref", "document_ref", "مرجع سند؟ (یا بنویس رد)", validator="non_empty"),
            StepDefinition("confirm", "confirm", "قرارداد ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
