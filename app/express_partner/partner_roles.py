# -*- coding: utf-8 -*-
"""سطوح همکار: عادی / بازاریاب / ویزیتور / پلاس."""
from __future__ import annotations

from typing import Any, Dict, Optional

APPROVED_PARTNER_STATUSES = frozenset({"approved", "active", "enabled", "ok", "true", "1"})
PARTNER_TIER_SPECIAL = "special"
PARTNER_TIER_VISITOR = "visitor"
PARTNER_TIER_PARTNER = "partner"

COOP_LEVEL_PLUS = "plus"
COOP_LEVEL_VISITOR = "visitor"
COOP_LEVEL_MARKETER = "marketer"
COOP_LEVEL_REGULAR = "regular"

_VISITOR_TIER_ALIASES = frozenset({PARTNER_TIER_VISITOR, "ویزیتور"})


def partner_is_approved(profile: Optional[Dict[str, Any]]) -> bool:
    if not profile or not isinstance(profile, dict):
        return False
    status = str(profile.get("status") or "").strip().lower()
    return profile.get("status") is True or status in APPROVED_PARTNER_STATUSES


def partner_tier(profile: Optional[Dict[str, Any]]) -> str:
    """partner | special — فقط اگر تأییدشده باشد معنا دارد."""
    if not partner_is_approved(profile):
        return ""
    tier = str((profile or {}).get("partner_tier") or "").strip().lower()
    if tier in (PARTNER_TIER_SPECIAL, "vip", "ویژه"):
        return PARTNER_TIER_SPECIAL
    return PARTNER_TIER_PARTNER


def partner_is_special(profile: Optional[Dict[str, Any]]) -> bool:
    if partner_tier(profile) != PARTNER_TIER_SPECIAL:
        return False
    from app.express_partner.plus_subscription import plus_subscription_active

    return plus_subscription_active(profile)


def partner_coop_level(profile: Optional[Dict[str, Any]]) -> str:
    """سطح ۱ پلاس، ۲ ویزیتور، ۳ بازاریاب، ۴ عادی."""
    if partner_is_special(profile):
        return COOP_LEVEL_PLUS
    if not partner_is_approved(profile):
        return COOP_LEVEL_REGULAR
    raw = str((profile or {}).get("partner_tier") or "").strip().lower()
    if raw in _VISITOR_TIER_ALIASES:
        return COOP_LEVEL_VISITOR
    return COOP_LEVEL_MARKETER


def partner_can_record_visit_attendance(profile: Optional[Dict[str, Any]]) -> bool:
    """ثبت «بازدید انجام شد» و «عدم حضور» فقط سطح ۱ و ۲."""
    return partner_coop_level(profile) in (COOP_LEVEL_PLUS, COOP_LEVEL_VISITOR)


def partner_can_manage_deal(profile: Optional[Dict[str, Any]]) -> bool:
    """تأیید / رد / بستن معامله فقط سطح ۱ پلاس و سطح ۲ ویزیتور."""
    return partner_coop_level(profile) in (COOP_LEVEL_PLUS, COOP_LEVEL_VISITOR)


def set_partner_tier(profile: Dict[str, Any], special: bool) -> None:
    if special:
        profile["partner_tier"] = PARTNER_TIER_SPECIAL
    else:
        profile["partner_tier"] = PARTNER_TIER_PARTNER
