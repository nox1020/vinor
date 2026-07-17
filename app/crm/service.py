# -*- coding: utf-8 -*-
"""Public CRM service — partner-facing helpers (fail-open when flags OFF)."""
from __future__ import annotations

from typing import Any, List, Optional

from app.crm import store
from app.crm.activity_hook import record_crm_event
from app.crm.config import (
    VISIT_CALL_TARGET,
    crm_activity_hook_enabled,
    crm_ai_tools_enabled,
    crm_enabled,
    crm_ui_enabled,
    crm_visit_sync_enabled,
)
from app.crm.interfaces import CallLog, Contact, FollowUp, Lead, Task


def crm_status() -> dict[str, Any]:
    """Observability helper — no side effects."""
    return {
        "crm_enabled": crm_enabled(),
        "crm_ui_enabled": crm_ui_enabled(),
        "crm_ai_tools_enabled": crm_ai_tools_enabled(),
        "crm_visit_sync_enabled": crm_visit_sync_enabled(),
        "crm_activity_hook_enabled": crm_activity_hook_enabled(),
        "visit_call_target": VISIT_CALL_TARGET,
        "phase": 1,
    }


def upsert_contact(**kwargs) -> Optional[Contact]:
    contact = store.upsert_contact(**kwargs)
    if contact is not None:
        record_crm_event(
            action="crm_contact_upsert",
            actor_key=contact.partner_phone,
            entity_type="contact",
            entity_id=contact.id,
            summary=f"Contact upsert: {contact.display_name or contact.customer_phone}",
            payload={"source": contact.source, "customer_phone": contact.customer_phone},
            subjects=[("contact", contact.id), ("partner", contact.partner_phone)],
        )
    return contact


def list_partner_customers(partner_phone: str, *, limit: int = 200) -> List[Contact]:
    return store.list_contacts(partner_phone=partner_phone, limit=limit)


def get_contact(contact_id: str) -> Optional[Contact]:
    return store.get_contact(contact_id)


def create_lead(**kwargs) -> Optional[Lead]:
    lead = store.create_lead(**kwargs)
    if lead is not None:
        record_crm_event(
            action="crm_lead_created",
            actor_key=lead.partner_phone,
            entity_type="lead",
            entity_id=lead.id,
            summary=f"Lead created: {lead.display_name}",
            payload={"customer_phone": lead.customer_phone},
            subjects=[("lead", lead.id), ("partner", lead.partner_phone)],
        )
    return lead


def list_partner_leads(partner_phone: str, *, status: str = "", limit: int = 200) -> List[Lead]:
    return store.list_leads(partner_phone=partner_phone, status=status, limit=limit)


def log_call(
    *,
    partner_phone: str,
    contact_id: str = "",
    lead_id: str = "",
    called_at: str = "",
    outcome: str = "",
    notes: str = "",
    to_number: str = "",
    metadata: dict[str, Any] | None = None,
) -> Optional[CallLog]:
    call = store.append_call_log(
        partner_phone=partner_phone,
        contact_id=contact_id,
        lead_id=lead_id,
        called_at=called_at,
        outcome=outcome,
        notes=notes,
        to_number=to_number or VISIT_CALL_TARGET,
        metadata=metadata,
    )
    if call is not None:
        record_crm_event(
            action="crm_call_logged",
            actor_key=call.partner_phone,
            entity_type="call_log",
            entity_id=call.id,
            summary=f"Call logged to {call.to_number}",
            payload={
                "contact_id": call.contact_id,
                "outcome": call.outcome,
                "to_number": call.to_number,
            },
            subjects=[
                ("call_log", call.id),
                ("partner", call.partner_phone),
                *(
                    [("contact", call.contact_id)]
                    if call.contact_id
                    else []
                ),
            ],
        )
    return call


def schedule_followup(
    *,
    partner_phone: str,
    contact_id: str = "",
    lead_id: str = "",
    due_at: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> Optional[FollowUp]:
    fu = store.create_followup(
        partner_phone=partner_phone,
        contact_id=contact_id,
        lead_id=lead_id,
        due_at=due_at,
        notes=notes,
        metadata=metadata,
    )
    if fu is not None:
        record_crm_event(
            action="crm_followup_scheduled",
            actor_key=fu.partner_phone,
            entity_type="followup",
            entity_id=fu.id,
            summary=f"Follow-up due {fu.due_at or '—'}",
            payload={"contact_id": fu.contact_id, "due_at": fu.due_at},
            subjects=[
                ("followup", fu.id),
                ("partner", fu.partner_phone),
                *(
                    [("contact", fu.contact_id)]
                    if fu.contact_id
                    else []
                ),
            ],
        )
    return fu


def list_partner_followups(
    partner_phone: str,
    *,
    contact_id: str = "",
    status: str = "",
    limit: int = 100,
) -> List[FollowUp]:
    return store.list_followups(
        partner_phone=partner_phone,
        contact_id=contact_id,
        status=status,
        limit=limit,
    )


def list_partner_calls(
    partner_phone: str,
    *,
    contact_id: str = "",
    limit: int = 100,
) -> List[CallLog]:
    return store.list_call_logs(
        partner_phone=partner_phone,
        contact_id=contact_id,
        limit=limit,
    )


def create_task(**kwargs) -> Optional[Task]:
    task = store.create_task(**kwargs)
    if task is not None:
        record_crm_event(
            action="crm_task_created",
            actor_key=task.partner_phone,
            entity_type="task",
            entity_id=task.id,
            summary=f"Task: {task.title}",
            payload={"contact_id": task.contact_id},
            subjects=[("task", task.id), ("partner", task.partner_phone)],
        )
    return task
