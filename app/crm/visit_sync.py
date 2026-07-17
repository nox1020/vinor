# -*- coding: utf-8 -*-
"""Visit → Contact sync. Read-only on Visit; never mutates Visit records."""
from __future__ import annotations

from typing import Any, Optional

from app.crm.config import crm_enabled, crm_visit_sync_enabled
from app.crm.interfaces import Contact


def sync_contact_from_visit(visit_rec: dict[str, Any] | None) -> Optional[Contact]:
    """
    Upsert Contact from Visit customer_* fields.
    Does not modify visit_rec. Fail-open / no-op when flags OFF.
    """
    if not crm_enabled() or not crm_visit_sync_enabled():
        return None
    if not isinstance(visit_rec, dict):
        return None
    try:
        partner_phone = str(visit_rec.get("partner_phone") or "").strip()
        customer_phone = str(visit_rec.get("customer_phone") or "").strip()
        if not partner_phone or not customer_phone:
            return None
        first_name = str(visit_rec.get("customer_first_name") or "").strip()
        last_name = str(visit_rec.get("customer_last_name") or "").strip()
        display = str(visit_rec.get("customer_name") or "").strip()
        visit_id = str(visit_rec.get("id") or "").strip()

        from app.crm.store import upsert_contact
        from app.crm.activity_hook import record_crm_event

        contact = upsert_contact(
            partner_phone=partner_phone,
            customer_phone=customer_phone,
            first_name=first_name,
            last_name=last_name,
            display_name=display,
            source="visit",
            visit_id=visit_id,
            metadata={
                "land_code": str(visit_rec.get("land_code") or "").strip(),
                "visit_date": str(visit_rec.get("visit_date") or "").strip(),
            },
        )
        if contact is not None:
            record_crm_event(
                action="crm_contact_upsert",
                actor_key=partner_phone,
                entity_type="contact",
                entity_id=contact.id,
                summary=f"Contact from visit: {contact.display_name or contact.customer_phone}",
                payload={
                    "source": "visit",
                    "visit_id": visit_id,
                    "customer_phone": contact.customer_phone,
                },
                subjects=[("contact", contact.id), ("partner", partner_phone)],
            )
        return contact
    except Exception:
        return None
