"""تشخیص مخاطب Vinor AI: همکار اکسپرس یا کاربر عادی."""
from __future__ import annotations

from typing import Any

AUDIENCE_PARTNER = "partner"
AUDIENCE_PUBLIC = "public"


def _norm_phone(phone: str) -> str:
    import re

    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def is_express_partner_profile(profile: dict[str, Any] | None) -> bool:
    if not profile or not isinstance(profile, dict):
        return False
    st = profile.get("status")
    if st in ("approved", True):
        return True
    if str(st or "").strip().lower() in ("pending", "under_review", "waiting", "review"):
        return True
    return False


def resolve_audience_for_session(
    *,
    phone: str = "",
    partner_profile: dict[str, Any] | None = None,
    force: str | None = None,
) -> str:
    if force in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC):
        return force
    if partner_profile is not None and is_express_partner_profile(partner_profile):
        return AUDIENCE_PARTNER
    if partner_profile is None and phone:
        try:
            from app.utils.storage import load_express_partners

            me = _norm_phone(phone)
            partners = load_express_partners() or []
            prof = next((p for p in partners if _norm_phone(str(p.get("phone") or "")) == me), None)
            if is_express_partner_profile(prof):
                return AUDIENCE_PARTNER
        except Exception:
            pass
    return AUDIENCE_PUBLIC


def resolve_audience_from_request(force: str | None = None) -> str:
    from flask import g, session

    phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, "express_partner_profile", None)
    return resolve_audience_for_session(phone=phone, partner_profile=profile, force=force)
