from __future__ import annotations

from app.workflow.definitions.deal import DealWorkflow
from app.workflow.definitions.general import GeneralConversationWorkflow
from app.workflow.definitions.partner_onboarding import PartnerWorkflow
from app.workflow.definitions.property_editing import PropertyEditingWorkflow
from app.workflow.definitions.property_registration import PropertyRegistrationWorkflow
from app.workflow.definitions.support import SupportWorkflow
from app.workflow.definitions.visit import VisitWorkflow
from app.workflow.interfaces import WorkflowObject

ALL_WORKFLOWS: list[WorkflowObject] = [
    PropertyRegistrationWorkflow(),
    PropertyEditingWorkflow(),
    PartnerWorkflow(),
    VisitWorkflow(),
    DealWorkflow(),
    SupportWorkflow(),
    GeneralConversationWorkflow(),
]
