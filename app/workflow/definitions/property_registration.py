from __future__ import annotations

from app.conversation.interfaces import INTENT_REGISTER_PROPERTY
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_PROPERTY_REGISTRATION, StepDefinition, WorkflowSpec


class PropertyRegistrationWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_PROPERTY_REGISTRATION,
        name="Property Registration",
        intent=INTENT_REGISTER_PROPERTY,
        object_type="PropertyRegistration",
        steps=[
            StepDefinition("property_type", "property_type", "نوع ملک چیست؟ (ویلا/زمین/باغ/آپارتمان)", validator="non_empty"),
            StepDefinition("city", "city", "شهر ملک کجاست؟", validator="non_empty"),
            StepDefinition("region", "region", "منطقه / محله؟", validator="non_empty"),
            StepDefinition("area", "area", "متراژ چند متر است؟", validator="area"),
            StepDefinition("price", "price", "قیمت پیشنهادی چقدر است؟", validator="price"),
            StepDefinition("amenities", "amenities", "امکانات مهم را بگویید.", validator="non_empty"),
            StepDefinition("photos", "photos", "آیا تصاویر آماده است؟ (بله/خیر یا توضیح)", validator="photos"),
            StepDefinition("deed", "deed", "وضعیت سند چیست؟", validator="non_empty"),
            StepDefinition("confirm", "confirm", "ثبت نهایی شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
