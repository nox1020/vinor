# -*- coding: utf-8 -*-
"""فعال‌سازی Vinor Plus پس از پرداخت موفق — partner_tier=special."""
from __future__ import annotations

from typing import Any, Dict, Optional

APPROVED_STATUSES = frozenset({"approved", "active", "enabled", "ok"})


def grant_vinor_plus_for_phone(
    phone: str,
    *,
    partner_name: str = "",
    subscription_days: int | None = None,
) -> Dict[str, Any]:
    """
    مدل محصول: همکار تأییدشده با partner_tier=special (همان is_special).
    اگر رکورد همکار نبود، رکورد minimal با status=approved ساخته می‌شود.
    """
    from app.express_partner.partner_roles import partner_tier, set_partner_tier, PARTNER_TIER_SPECIAL
    from app.express_partner.partner_session_sync import canonical_partner_phone
    from app.utils.storage import load_express_partners, save_express_partners

    ph = canonical_partner_phone(str(phone or "").strip())
    if not ph:
        return {"ok": False, "error": "missing_phone"}

    partners = load_express_partners() or []
    if not isinstance(partners, list):
        partners = []

    found: Optional[Dict[str, Any]] = None
    for p in partners:
        if not isinstance(p, dict):
            continue
        pph = canonical_partner_phone(str(p.get("phone") or "").strip())
        if pph == ph:
            found = p
            break

    if found is None:
        found = {
            "phone": ph,
            "name": (partner_name or "").strip() or ph,
            "status": "approved",
        }
        partners.append(found)
    else:
        st = str(found.get("status") or "").strip().lower()
        if found.get("status") is not True and st not in APPROVED_STATUSES:
            found["status"] = "approved"
        if partner_name and not str(found.get("name") or "").strip():
            found["name"] = partner_name.strip()

    from app.express_partner.plus_subscription import (
        PLUS_GRANTED_AT_KEY,
        extend_plus_subscription,
    )
    from app.express_partner.zarinpal_config import plus_subscription_days
    from app.utils.dates import iso_z, utcnow

    already = partner_tier(found) == PARTNER_TIER_SPECIAL
    set_partner_tier(found, True)
    days = subscription_days
    if days is None:
        days = plus_subscription_days()
    days = max(1, int(days or 0))
    if not str(found.get(PLUS_GRANTED_AT_KEY) or "").strip():
        found[PLUS_GRANTED_AT_KEY] = iso_z(utcnow())
    expires_at = extend_plus_subscription(found, days)
    try:
        save_express_partners(partners)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "already_special": already,
        "phone": ph,
        "plus_expires_at": expires_at,
        "subscription_days_added": int(days) if days else 0,
    }
