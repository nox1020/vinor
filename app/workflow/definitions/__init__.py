from __future__ import annotations

from app.workflow.definitions.deal import DealWorkflow
from app.workflow.definitions.general import GeneralConversationWorkflow
from app.workflow.definitions.offer import OfferWorkflow
from app.workflow.definitions.partner_onboarding import PartnerWorkflow
from app.workflow.definitions.property_editing import PropertyEditingWorkflow
from app.workflow.definitions.property_registration import PropertyRegistrationWorkflow
from app.workflow.definitions.support import SupportWorkflow
from app.workflow.definitions.visit import VisitWorkflow
from app.workflow.definitions.visit_result import VisitResultWorkflow
from app.workflow.definitions.crm_followup import CrmFollowupWorkflow
from app.workflow.definitions.closing_contract import ClosingContractWorkflow
from app.workflow.interfaces import WorkflowObject

ALL_WORKFLOWS: list[WorkflowObject] = [
    PropertyRegistrationWorkflow(),
    PropertyEditingWorkflow(),
    PartnerWorkflow(),
    VisitWorkflow(),
    DealWorkflow(),
    OfferWorkflow(),
    VisitResultWorkflow(),
    CrmFollowupWorkflow(),
    ClosingContractWorkflow(),
    SupportWorkflow(),
    GeneralConversationWorkflow(),
]
