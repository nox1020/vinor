from __future__ import annotations

from app.conversation.interfaces import INTENT_BECOME_PARTNER
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_PARTNER_ONBOARDING, StepDefinition, WorkflowSpec


class PartnerWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_PARTNER_ONBOARDING,
        name="Partner Onboarding",
        intent=INTENT_BECOME_PARTNER,
        object_type="PartnerApplication",
        steps=[
            StepDefinition("name", "name", "نام و نام‌خانوادگی‌تان چیست؟", validator="non_empty"),
            StepDefinition("national_id", "national_id", "کد ملی را وارد کنید.", validator="national_id"),
            StepDefinition("city", "city", "شهر فعالیت‌تان کجاست؟", validator="non_empty"),
            StepDefinition("experience", "experience", "سابقه فروش ملک‌تان را کوتاه بگویید.", validator="non_empty"),
            StepDefinition("confirm", "confirm", "درخواست همکاری ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
