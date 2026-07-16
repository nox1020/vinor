from __future__ import annotations

from app.conversation.interfaces import INTENT_EDIT_PROPERTY
from app.workflow.definitions.base import BaseWorkflow
from app.workflow.interfaces import WF_PROPERTY_EDITING, StepDefinition, WorkflowSpec


class PropertyEditingWorkflow(BaseWorkflow):
    spec = WorkflowSpec(
        id=WF_PROPERTY_EDITING,
        name="Property Editing",
        intent=INTENT_EDIT_PROPERTY,
        object_type="PropertyEdit",
        steps=[
            StepDefinition("land_code", "land_code", "کد فایل برای ویرایش چیست؟", validator="land_code"),
            StepDefinition("field_name", "field_name", "کدام فیلد را تغییر می‌دهید؟ (قیمت/متراژ/منطقه/…)", validator="non_empty"),
            StepDefinition("new_value", "new_value", "مقدار جدید چیست؟", validator="non_empty"),
            StepDefinition("confirm", "confirm", "ویرایش ثبت شود؟ (بله / خیر)", validator="yes_no"),
        ],
    )
