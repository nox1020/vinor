from __future__ import annotations

from app.conversation.interfaces import INTENT_DEAL
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_DEAL, StepDefinition, WorkflowSpec


class DealWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_DEAL,
        name="Property Deal",
        intent=INTENT_DEAL,
        object_type="DealRequest",
        steps=[
            StepDefinition("land_code", "land_code", "کد فایل معامله چیست؟", validator="land_code"),
            StepDefinition("deal_type", "deal_type", "نوع معامله؟ (فروش / پیش‌فروش)", validator="deal_type"),
            StepDefinition("amount", "amount", "مبلغ معامله؟", validator="price"),
            StepDefinition("confirm", "confirm", "معامله ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
