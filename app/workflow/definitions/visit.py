from __future__ import annotations

from app.conversation.interfaces import INTENT_VISIT
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_VISIT, StepDefinition, WorkflowSpec


class VisitWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_VISIT,
        name="Property Visit",
        intent=INTENT_VISIT,
        object_type="VisitRequest",
        steps=[
            StepDefinition("land_code", "land_code", "کد فایل برای بازدید چیست؟", validator="land_code"),
            StepDefinition("visitor_name", "visitor_name", "نام بازدیدکننده؟", validator="non_empty"),
            StepDefinition("visitor_phone", "visitor_phone", "شماره موبایل بازدیدکننده؟", validator="phone"),
            StepDefinition("visit_date", "visit_date", "تاریخ بازدید؟", validator="non_empty"),
            StepDefinition("confirm", "confirm", "بازدید ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
