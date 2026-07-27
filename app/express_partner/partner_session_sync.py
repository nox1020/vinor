# -*- coding: utf-8 -*-
"""همگام‌سازی سشن و g پس از تغییر پروفایل همکار (مثلاً Vinor Plus)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def canonical_partner_phone(phone: str) -> str:
    """همان فرمت 09xxxxxxxxx که در OTP و JSON همکار استفاده می‌شود."""
    from app.services.notifications import _normalize_user_id
    from app.services.sms import normalize_iran_mobile

    raw = _normalize_user_id(str(phone or "").strip())
    return normalize_iran_mobile(raw) or raw


def find_partner_record(partners: List[Dict[str, Any]], phone: str) -> Optional[Dict[str, Any]]:
    raw = (phone or "").strip()
    if not raw:
        return None
    norm = canonical_partner_phone(raw)
    for p in partners:
        if not isinstance(p, dict):
            continue
        p_phone = str(p.get("phone") or "").strip()
        if not p_phone:
            continue
        if p_phone == raw or p_phone == norm or canonical_partner_phone(p_phone) == norm:
            return p
    return None


def sync_partner_session_after_plus(phone: str) -> None:
    """پس از grant پلاس: کش درخواست، پروفایل g و پرچم‌های سشن را تازه کن."""
    from flask import g, has_request_context, session

    from app.utils.storage import load_express_partners

    from .partner_roles import partner_is_approved, partner_is_special

    if not has_request_context():
        return

    ph = canonical_partner_phone(phone)
    if not ph:
        return

    for key in (
        "_express_partners_list_cached",
        "_express_partner_by_phone",
        "_express_partner_ctx_ready",
        "express_partner_profile",
    ):
        if hasattr(g, key):
            try:
                delattr(g, key)
            except Exception:
                pass

    partners = load_express_partners() or []
    if not isinstance(partners, list):
        partners = []
    profile = find_partner_record(partners, ph)

    from .plus_subscription import persist_plus_expiry_backfill_for_phone

    if persist_plus_expiry_backfill_for_phone(ph):
        partners = load_express_partners() or []
        if not isinstance(partners, list):
            partners = []
        profile = find_partner_record(partners, ph)

    g._express_partners_list_cached = partners
    g._express_partner_ctx_ready = True
    g.express_partner_profile = profile

    try:
        session["VINOR_IS_EXPRESS_PARTNER"] = bool(partner_is_approved(profile))
        session["VINOR_PLUS_ACTIVE"] = bool(partner_is_special(profile))
        session.modified = True
    except Exception:
        pass


def phones_match(a: str, b: str) -> bool:
    pa = canonical_partner_phone(a)
    pb = canonical_partner_phone(b)
    return bool(pa and pb and pa == pb)
