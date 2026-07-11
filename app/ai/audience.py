"""تشخیص مخاطب و لحن Vinor AI: مشتری | همکار | همکار ویژه."""
from __future__ import annotations

from typing import Any

AUDIENCE_PARTNER = "partner"
AUDIENCE_PUBLIC = "public"

# لحن گفتگو (جدا از کلید ذخیره‌سازی چت)
VOICE_PUBLIC = "public"
VOICE_PARTNER = "partner"
VOICE_SPECIAL = "special"


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
    if force in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC):
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
    - public: مشتری / خریدار
    - partner: همکار پورسانت‌گیر (واسط فروشنده و خریدار)
    - special: همکار ویژه (مالک/فروشنده با بیشترین دسترسی)
    """
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


def voice_label_fa(voice: str | None) -> str:
    v = (voice or "").strip().lower()
    if v == VOICE_SPECIAL:
        return "همکار ویژه (مالک/فروشنده)"
    if v == VOICE_PARTNER:
        return "همکار اکسپرس (واسط فروش)"
    return "مشتری / خریدار"


def resolve_audience_from_request(force: str | None = None) -> str:
    from flask import g, session

    phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, "express_partner_profile", None)
    return resolve_audience_for_session(phone=phone, partner_profile=profile, force=force)


def resolve_voice_from_request(audience: str | None = None) -> str:
    from flask import g, session

    phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, "express_partner_profile", None)
    return resolve_ai_voice(phone=phone, partner_profile=profile, audience=audience)
