# -*- coding: utf-8 -*-
"""مدت اشتراک Vinor Plus — plus_expires_at روی رکورد همکار."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from app.utils.dates import format_display_jalali_date, iso_z, parse_iso_to_naive_utc, utcnow

PLUS_EXPIRES_AT_KEY = "plus_expires_at"
PLUS_GRANTED_AT_KEY = "plus_granted_at"
DEFAULT_SUBSCRIPTION_DAYS = 30
PLUS_RENEW_WINDOW_DAYS = 7


def parse_plus_expires_at(profile: Optional[Dict[str, Any]]) -> Optional[datetime]:
    if not profile or not isinstance(profile, dict):
        return None
    raw = str(profile.get(PLUS_EXPIRES_AT_KEY) or "").strip()
    if not raw:
        return None
    dt = parse_iso_to_naive_utc(raw)
    if dt is None:
        d_only = raw[:10]
        dt = parse_iso_to_naive_utc(f"{d_only}T23:59:59Z")
    return dt


def plus_has_expiry_field(profile: Optional[Dict[str, Any]]) -> bool:
    if not profile or not isinstance(profile, dict):
        return False
    return bool(str(profile.get(PLUS_EXPIRES_AT_KEY) or "").strip())


def plus_subscription_expired(profile: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> bool:
    """وقتی plus_expires_at تنظیم شده و گذشته — منقضی؛ بدون تاریخ = منقضی نشده (تا backfill)."""
    exp = parse_plus_expires_at(profile)
    if exp is None:
        return False
    ref = now if now is not None else utcnow()
    return exp <= ref


def _subscription_days_default() -> int:
    try:
        from app.express_partner.zarinpal_config import plus_subscription_days

        return max(1, int(plus_subscription_days()))
    except Exception:
        return DEFAULT_SUBSCRIPTION_DAYS


def backfill_plus_expires_at(
    profile: Dict[str, Any],
    *,
    days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> bool:
    """
    مهاجرت legacy: همکار special بدون plus_expires_at دیگر «نامحدود» نیست.
    یک‌بار تاریخ پایان می‌گذارد: plus_granted_at + مدت (اگر بود) وگرنه now + مدت اشتراک.
    """
    from app.express_partner.partner_roles import PARTNER_TIER_SPECIAL, partner_tier

    if partner_tier(profile) != PARTNER_TIER_SPECIAL:
        return False
    if plus_has_expiry_field(profile):
        return False
    ref = now if now is not None else utcnow()
    d = max(1, int(days if days is not None else _subscription_days_default()))
    anchor = ref
    raw_granted = str(profile.get(PLUS_GRANTED_AT_KEY) or "").strip()
    if raw_granted:
        granted = parse_iso_to_naive_utc(raw_granted)
        if granted is not None:
            anchor = granted
    profile[PLUS_EXPIRES_AT_KEY] = iso_z(anchor + timedelta(days=d))
    return True


def persist_plus_expiry_backfill_for_phone(phone: str) -> bool:
    """اگر special بدون تاریخ پایان باشد، backfill و ذخیره در express_partners.json."""
    from app.express_partner.partner_session_sync import canonical_partner_phone, find_partner_record
    from app.utils.storage import load_express_partners, save_express_partners

    ph = canonical_partner_phone(str(phone or "").strip())
    if not ph:
        return False
    partners = load_express_partners() or []
    if not isinstance(partners, list):
        partners = []
    profile = find_partner_record(partners, ph)
    if not isinstance(profile, dict):
        return False
    if not backfill_plus_expires_at(profile):
        return False
    try:
        save_express_partners(partners)
        return True
    except Exception:
        return False


def plus_subscription_active(profile: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> bool:
    """tier=special با plus_expires_at در آینده؛ بدون تاریخ پایان = غیرفعال تا backfill."""
    if not profile or not isinstance(profile, dict):
        return False
    if not plus_has_expiry_field(profile):
        return False
    exp = parse_plus_expires_at(profile)
    if exp is None:
        return False
    ref = now if now is not None else utcnow()
    return exp > ref


def renewal_anchor(now: Optional[datetime] = None, current_expiry: Optional[datetime] = None) -> datetime:
    """پایهٔ تمدید: از پایان فعلی اگر هنوز فعال است، وگرنه از الان."""
    ref = now if now is not None else utcnow()
    if current_expiry is not None and current_expiry > ref:
        return current_expiry
    return ref


def extend_plus_subscription(
    profile: Dict[str, Any],
    days: int,
    *,
    now: Optional[datetime] = None,
) -> str:
    """روزها را به اشتراک اضافه می‌کند؛ ISO UTC در plus_expires_at."""
    d = max(0, int(days))
    ref = now if now is not None else utcnow()
    anchor = renewal_anchor(ref, parse_plus_expires_at(profile))
    new_exp = anchor + timedelta(days=d)
    iso = iso_z(new_exp)
    profile[PLUS_EXPIRES_AT_KEY] = iso
    return iso


def days_remaining(profile: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> Optional[int]:
    exp = parse_plus_expires_at(profile)
    if exp is None:
        return None
    ref = now if now is not None else utcnow()
    if exp <= ref:
        return 0
    total = int((exp - ref).total_seconds())
    return max(1, (total + 86400 - 1) // 86400)


def plus_subscription_view(profile: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    وضعیت نمایشی صفحهٔ پلاس.
    status: none | active | expired
    """
    from app.express_partner.partner_roles import PARTNER_TIER_SPECIAL, partner_tier

    ref = now if now is not None else utcnow()
    empty = {"status": "none", "expires_at": "", "expires_at_jalali": "", "days_remaining": None}
    if not profile or not isinstance(profile, dict):
        return dict(empty)
    if partner_tier(profile) != PARTNER_TIER_SPECIAL:
        return dict(empty)

    if not plus_has_expiry_field(profile):
        backfill_plus_expires_at(profile, now=ref)

    exp = parse_plus_expires_at(profile)
    iso = str(profile.get(PLUS_EXPIRES_AT_KEY) or "").strip()
    jalali = format_display_jalali_date(iso[:10]) if iso else ""
    rem = days_remaining(profile, now=ref)
    if exp is not None and exp <= ref:
        return {
            "status": "expired",
            "expires_at": iso,
            "expires_at_jalali": jalali,
            "days_remaining": 0,
        }
    return {
        "status": "active",
        "expires_at": iso,
        "expires_at_jalali": jalali,
        "days_remaining": rem,
    }


def plus_period_label(days: int) -> str:
    d = max(1, int(days))
    if d == 365:
        return "سالانه"
    return f"{d} روز"


def plus_renew_allowed(profile: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> bool:
    """
    تمدید پرداخت آنلاین برای اشتراک فعال فقط در بازهٔ پایانی (PLUS_RENEW_WINDOW_DAYS) مجاز است.
    کاربر منقضی‌شده از شاخهٔ خرید/تمدید صفحه استفاده می‌کند — همیشه مجاز.
    """
    view = plus_subscription_view(profile, now=now)
    status = str(view.get("status") or "none")
    if status == "expired":
        return True
    if status != "active":
        return False
    rem = view.get("days_remaining")
    if rem is None:
        return False
    return int(rem) <= PLUS_RENEW_WINDOW_DAYS
