# -*- coding: utf-8 -*-
"""Partner CRM customers helpers — list + enrichment for UI."""
from __future__ import annotations

from typing import Any, Dict, List

from app.crm.service import list_partner_calls, list_partner_customers, list_partner_followups

# همهٔ تماس‌ها/پیگیری‌های همکار یک‌بار خوانده و بر اساس مشتری گروه می‌شوند.
_SCAN_LIMIT = 100_000
_PER_CONTACT = 3


def partner_customers_view(partner_phone: str) -> List[dict[str, Any]]:
    """Contacts for partner with recent call/follow-up counts (for template and APK JSON).

    قبلاً برای هر مشتری (تا ۲۰۰) دو بار کل فایل تماس‌ها و پیگیری‌ها از دیسک خوانده می‌شد
    (۱ + ۲N بار json.load و نرمال‌سازی شمارهٔ همهٔ ردیف‌ها) و تب «مشتریان» کند بود.
    حالا هر فایل فقط یک‌بار خوانده می‌شود؛ ترتیب (جدیدترین اول) و سقف ۳ مورد همان است.
    """
    contacts = list_partner_customers(partner_phone, limit=200)
    if not contacts:
        return []
    wanted = {c.id for c in contacts}
    calls_by: Dict[str, list] = {}
    for x in list_partner_calls(partner_phone, limit=_SCAN_LIMIT):
        cid = str(getattr(x, "contact_id", "") or "")
        if cid in wanted:
            bucket = calls_by.setdefault(cid, [])
            if len(bucket) < _PER_CONTACT:
                bucket.append(x)
    fus_by: Dict[str, list] = {}
    for x in list_partner_followups(partner_phone, status="pending", limit=_SCAN_LIMIT):
        cid = str(getattr(x, "contact_id", "") or "")
        if cid in wanted:
            bucket = fus_by.setdefault(cid, [])
            if len(bucket) < _PER_CONTACT:
                bucket.append(x)
    out: List[dict[str, Any]] = []
    for c in contacts:
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
                    for x in calls_by.get(c.id, [])
                ],
                "pending_followups": [
                    {
                        "id": x.id,
                        "due_at": x.due_at,
                        "notes": x.notes,
                    }
                    for x in fus_by.get(c.id, [])
                ],
            }
        )
    return out


CUSTOMER_FIELDS = [
    {"name": "first_name", "label": "نام", "required": True, "phone": False, "multiline": False},
    {"name": "last_name", "label": "نام خانوادگی", "required": True, "phone": False, "multiline": False},
    {"name": "customer_phone", "label": "شماره مشتری", "required": True, "phone": True, "multiline": False},
]


def customers_payload(partner_phone: str, *, csrf_token: str, visit_call_target: str) -> dict[str, Any]:
    """JSON سبک برای تب «مشتریان» اپ — به‌جای اسکرپ کل HTML صفحه."""
    return {
        "ok": True,
        "csrf_token": csrf_token,
        "customers": partner_customers_view(partner_phone),
        "fields": CUSTOMER_FIELDS,
        "submit_label": "ذخیره مشتری",
        "action_path": "/express/partner/customers",
        "empty_text": "هنوز مشتری‌ای ثبت نشده",
        "visit_call_target": visit_call_target,
    }
