# -*- coding: utf-8 -*-
"""Offer form workflow — Phase 3 Commercial (gated by VINOR_COMMERCIAL_WORKFLOW_ENABLED)."""
from __future__ import annotations

from app.conversation.interfaces import INTENT_OFFER
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_OFFER, StepDefinition, WorkflowSpec


class OfferWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_OFFER,
        name="Commercial Offer",
        intent=INTENT_OFFER,
        object_type="OfferRequest",
        steps=[
            StepDefinition("land_code", "land_code", "", validator="land_code"),
            StepDefinition("amount", "amount", "مبلغ پیشنهاد؟", validator="price"),
            StepDefinition("buyer_phone", "buyer_phone", "شماره خریدار؟ (یا بنویس رد)", validator="non_empty"),
            StepDefinition("confirm", "confirm", "پیشنهاد ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
