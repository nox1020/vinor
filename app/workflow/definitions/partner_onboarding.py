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
            StepDefinition("first_name", "first_name", "نام‌تان چیست؟", validator="non_empty"),
            StepDefinition("last_name", "last_name", "نام خانوادگی‌تان چیست؟", validator="non_empty"),
            StepDefinition("national_id", "national_id", "کد ملی را وارد کنید.", validator="national_id"),
            StepDefinition("confirm", "confirm", "همکاری ثبت و فعال شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
