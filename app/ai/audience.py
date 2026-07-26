"""تشخیص مخاطب و لحن Vinor AI.

- public / partner / special: بازاریاب فروش (هدف قفل در roadmap/AGENT_GOAL.md)
- admin: دستیار عملیات پنل ادمین — نه فروش مشتری
"""
from __future__ import annotations

from typing import Any

AUDIENCE_PARTNER = "partner"
AUDIENCE_PUBLIC = "public"
AUDIENCE_ADMIN = "admin"

# لحن گفتگو (جدا از کلید ذخیره‌سازی چت)
VOICE_PUBLIC = "public"
VOICE_PARTNER = "partner"
VOICE_SPECIAL = "special"
VOICE_ADMIN = "admin"
VOICE_LAWYER = "lawyer"


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


def _load_partner_profile(phone: str) -> dict[str, Any] | None:
    me = _norm_phone(phone)
    if not me:
        return None
    try:
        from app.utils.storage import load_express_partners

        partners = load_express_partners() or []
        return next(
            (p for p in partners if _norm_phone(str(p.get("phone") or "")) == me),
            None,
        )
    except Exception:
        return None


def resolve_audience_for_session(
    *,
    phone: str = "",
    partner_profile: dict[str, Any] | None = None,
    force: str | None = None,
) -> str:
    if force in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC, AUDIENCE_ADMIN):
        return force
    if partner_profile is not None and is_express_partner_profile(partner_profile):
        return AUDIENCE_PARTNER
    if partner_profile is None and phone:
        prof = _load_partner_profile(phone)
        if is_express_partner_profile(prof):
            return AUDIENCE_PARTNER
    return AUDIENCE_PUBLIC


def resolve_ai_voice(
    *,
    phone: str = "",
    partner_profile: dict[str, Any] | None = None,
    audience: str | None = None,
) -> str:
    """
    لحن پاسخ:
    - admin: دستیار عملیات (نه فروش مشتری)
    - public / partner / special: بازاریاب فروش (AGENT_GOAL.md)
    """
    if audience == AUDIENCE_ADMIN:
        return VOICE_ADMIN
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else None
    prof = partner_profile
    if prof is None and phone:
        prof = _load_partner_profile(phone)

    if aud == AUDIENCE_PUBLIC:
        return VOICE_PUBLIC
    if aud == AUDIENCE_PARTNER or is_express_partner_profile(prof):
        try:
            from app.express_partner.partner_roles import partner_is_special

            if partner_is_special(prof):
                return VOICE_SPECIAL
        except Exception:
            pass
        return VOICE_PARTNER
    if is_express_partner_profile(prof):
        return VOICE_PARTNER
    return VOICE_PUBLIC


