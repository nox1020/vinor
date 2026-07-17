# -*- coding: utf-8 -*-
"""Partner CRM customers helpers — list + enrichment for UI."""
from __future__ import annotations

from typing import Any, List

from app.crm.service import list_partner_calls, list_partner_customers, list_partner_followups


def partner_customers_view(partner_phone: str) -> List[dict[str, Any]]:
    """Contacts for partner with recent call/follow-up counts (for template)."""
    contacts = list_partner_customers(partner_phone, limit=200)
    out: List[dict[str, Any]] = []
    for c in contacts:
        calls = list_partner_calls(partner_phone, contact_id=c.id, limit=5)
        fus = list_partner_followups(partner_phone, contact_id=c.id, status="pending", limit=5)
        out.append(
            {
                "id": c.id,
                "display_name": c.display_name or c.customer_phone,
                "first_name": c.first_name,
                "last_name": c.last_name,
                "customer_phone": c.customer_phone,
                "source": c.source,
                "visit_count": len(c.visit_ids or []),
                "recent_calls": [
                    {
                        "id": x.id,
                        "called_at": x.called_at,
                        "outcome": x.outcome,
                        "to_number": x.to_number,
                        "notes": x.notes,
                    }
                    for x in calls[:3]
                ],
                "pending_followups": [
                    {
                        "id": x.id,
                        "due_at": x.due_at,
                        "notes": x.notes,
                    }
                    for x in fus[:3]
                ],
            }
        )
    return out
