# -*- coding: utf-8 -*-
"""
Vinor CRM Layer (Phase 1)

Additive Lead / Contact / Call / Follow-up / Task with Visit sync.
All feature flags default ON — disable via env if needed. Existing Visit/Deal/Commission/Withdrawal unchanged when flags are off.
"""

from app.crm.config import (
    VISIT_CALL_TARGET,
    crm_activity_hook_enabled,
    crm_ai_tools_enabled,
    crm_enabled,
    crm_ui_enabled,
    crm_visit_sync_enabled,
)
from app.crm.service import (
    crm_status,
    create_lead,
    create_task,
    get_contact,
    list_partner_calls,
    list_partner_customers,
    list_partner_followups,
    list_partner_leads,
    log_call,
    schedule_followup,
    upsert_contact,
)
from app.crm.visit_sync import sync_contact_from_visit

__all__ = [
    "VISIT_CALL_TARGET",
    "crm_enabled",
    "crm_ui_enabled",
    "crm_ai_tools_enabled",
    "crm_visit_sync_enabled",
    "crm_activity_hook_enabled",
    "crm_status",
    "upsert_contact",
    "get_contact",
    "list_partner_customers",
    "create_lead",
    "list_partner_leads",
    "log_call",
    "schedule_followup",
    "list_partner_followups",
    "list_partner_calls",
    "create_task",
    "sync_contact_from_visit",
]
