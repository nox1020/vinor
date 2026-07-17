# -*- coding: utf-8 -*-
"""Map existing user/partner/special/admin → portal roles (fail-open, no OTP mutate)."""
from __future__ import annotations

from typing import Any, List, Set

from app.roles.config import (
    roles_enabled,
    roles_super_admin_enabled,
    super_admin_phones,
)
from app.roles.interfaces import (
    PORTAL_BUYER,
    PORTAL_OWNER,
    PORTAL_SELLER,
    PORTAL_SUPER_ADMIN,
)


def _norm_phone(phone: str) -> str:
    raw = (phone or "").strip()
    if not raw:
        return ""
    try:
        from app.services.sms import normalize_iran_mobile

        return normalize_iran_mobile(raw) or raw
    except Exception:
        return raw


def map_roles_from_identity(
    *,
    phone: str = "",
    session: Any = None,
    partner_profile: dict[str, Any] | None = None,
) -> List[str]:
    """
    Derive portal roles from existing Vinor identity — never writes session/OTP.
    """
    if not roles_enabled():
        return []
    mapped: Set[str] = set()
    pp = _norm_phone(phone)
    sess = session
    if sess is None:
        try:
            from flask import session as flask_session

            sess = flask_session
        except Exception:
            sess = None

    # buyer: any logged-in user phone
    user_phone = ""
    if sess is not None:
        try:
            user_phone = _norm_phone(str(sess.get("user_phone") or ""))
        except Exception:
            user_phone = ""
    if not user_phone:
        user_phone = pp
    if user_phone:
        mapped.add(PORTAL_BUYER)

    # partner profile lookup
    profile = partner_profile if isinstance(partner_profile, dict) else None
    if profile is None and user_phone:
        try:
            from app.utils.storage import load_express_partners
            from app.express_partner.partner_roles import partner_is_approved

            partners = load_express_partners() or []
            for p in partners:
                if not isinstance(p, dict):
                    continue
                if _norm_phone(str(p.get("phone") or "")) == user_phone:
                    profile = p
                    break
            # also try canonical helpers if available
            _ = partner_is_approved  # imported for clarity
        except Exception:
            profile = None

    try:
        from app.express_partner.partner_roles import partner_is_approved, partner_is_special

        if partner_is_approved(profile):
            mapped.add(PORTAL_SELLER)
        if partner_is_special(profile):
            mapped.add(PORTAL_OWNER)
    except Exception:
        pass

    # owner via listings ownership (special listings) even without special tier
    if user_phone and PORTAL_OWNER not in mapped:
        try:
            from app.express_partner.special_listings import listings_owned_by

            if listings_owned_by(user_phone):
                mapped.add(PORTAL_OWNER)
        except Exception:
            pass

    # super_admin: admin logged_in + allowlist (empty allowlist = any admin)
    if roles_super_admin_enabled() and sess is not None:
        try:
            if bool(sess.get("logged_in")):
                allow = [_norm_phone(x) for x in super_admin_phones()]
                allow = [x for x in allow if x]
                admin_phone = _norm_phone(
                    str(sess.get("admin_phone") or sess.get("username") or "")
                )
                # Admin OTP phone used by Vinor admin login (see admin/routes.py)
                check_phone = admin_phone or user_phone or _norm_phone("09121471301")
                if not allow or (check_phone and check_phone in allow):
                    mapped.add(PORTAL_SUPER_ADMIN)
        except Exception:
            pass

    order = [PORTAL_BUYER, PORTAL_SELLER, PORTAL_OWNER, PORTAL_SUPER_ADMIN]
    return [r for r in order if r in mapped]
