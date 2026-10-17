# -*- coding: utf-8 -*-
"""یک پیامک به مالک، ۷۲ ساعت بعد از انتشار، اگر هنوز درخواست بازدید نیست.

هر چرخهٔ published_at فقط یک‌بار. نشانه روی خود آگهی می‌ماند تا بعد از
انتشار دوباره (published_at تازه) دوباره مجاز باشد.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from app.listings.performance import listing_performance, load_visit_rows, parse_ts
from app.listings.service import (
    _cycle_stamp,
    _read_json,
    code_key,
    is_published_for_sale,
    listings_lock,
    listings_path,
    owner_phone,
    save_listings,
)
from app.utils.dates import utcnow

QUIET_AFTER = timedelta(hours=72)
_MARKER = "quiet_nudge_published_at"
_FEW_PHOTOS = 2


def quiet_nudge_enabled() -> bool:
    return (os.environ.get("VINOR_LISTING_QUIET_NUDGE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _photo_count(land: Dict[str, Any]) -> int:
    images = land.get("images") or []
    if isinstance(images, str):
        return 1 if images.strip() else 0
    if isinstance(images, list):
        return len([item for item in images if item])
    return 0


def _commission_pct(land: Dict[str, Any]) -> float:
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    raw = extras.get("express_commission_pct", land.get("express_commission_pct"))
    try:
        if raw in (None, ""):
            return 0.0
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def suggestion_for(land: Dict[str, Any]) -> str:
    """یک کار مشخص: عکس اگر کم است، وگرنه تعیین یا افزایش پورسانت."""
    if _photo_count(land) < _FEW_PHOTOS:
        return "یک عکس از ملک اضافه کنید تا همکاران درخواست بازدید بدهند."
    if _commission_pct(land) <= 0:
        return "پورسانت همکاری را مشخص کنید تا همکاران برای بازدید انگیزه داشته باشند."
    return "پورسانت همکاری را کمی بالاتر بگذارید تا درخواست بازدید بیشتر شود."


def _fa_digits(value: int) -> str:
    return str(int(value)).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def my_property_url() -> str:
    try:
        from flask import url_for

        return url_for("express_partner.my_property", _external=True)
    except Exception:
        return "https://vinor.ir/express/partner/my-property"


def build_quiet_listing_sms(*, views: int, suggestion: str, link: str, code: str) -> str:
    return (
        "وینور\n"
        f"۳ روز از انتشار آگهی {code} گذشته و هنوز درخواست بازدید نیست.\n"
        f"{_fa_digits(views)} همکار آگهی را دیده‌اند.\n"
        f"{suggestion}\n"
        f"ملک من: {link}"
    )


def _default_sender(phone: str, message: str) -> Dict[str, Any]:
    from app.services.sms import send_sms_direct

    return send_sms_direct(
        phone,
        message,
        history_source="listing_quiet_nudge",
        record_history=True,
    )


def _owner_mobile(land: Dict[str, Any]) -> str:
    try:
        from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

        phone = normalize_iran_mobile(owner_phone(land)) or ""
        if is_valid_iran_mobile(phone):
            return phone
    except Exception:
        return ""
    return ""


def _due(land: Dict[str, Any], now: datetime, visits: List[dict]) -> bool:
    if not is_published_for_sale(land):
        return False
    published_at = _cycle_stamp(land, "published_at")
    start = parse_ts(published_at)
    if not published_at or start is None or now < start + QUIET_AFTER:
        return False
    if _cycle_stamp(land, _MARKER) == published_at:
        return False
    stats = listing_performance(land, now=now, views=[], visits=visits)
    if int(stats.get("visit_requests_total") or 0) > 0:
        return False
    return bool(_owner_mobile(land))


def _claim(
    code: str,
    published_at: str,
    now: datetime,
    app=None,
) -> Optional[Dict[str, Any]]:
    """نشانه را قبل از ارسال بنویس تا دو نوبت همزمان یک پیامک نسازند."""
    with listings_lock(app):
        items = _read_json(listings_path(app))
        if not isinstance(items, list):
            return None
        visits = load_visit_rows(app)
        matched = [
            land
            for land in items
            if isinstance(land, dict)
            and code_key(land) == code
            and _cycle_stamp(land, "published_at") == published_at
            and _due(land, now, visits)
        ]
        if not matched:
            return None
        land = matched[0]
        for row in matched:
            extras = dict(row.get("extras") or {}) if isinstance(row.get("extras"), dict) else {}
            extras[_MARKER] = published_at
            row["extras"] = extras
            row[_MARKER] = published_at
        save_listings(items, app)
        stats = listing_performance(land, now=now, visits=visits, app=app)
        return {
            "code": code,
            "phone": _owner_mobile(land),
            "published_at": published_at,
            "message": build_quiet_listing_sms(
                views=int(stats.get("views_since_publish") or 0),
                suggestion=suggestion_for(land),
                link=my_property_url(),
                code=code,
            ),
        }


def _release(code: str, published_at: str, app=None) -> None:
    with listings_lock(app):
        items = _read_json(listings_path(app))
        if not isinstance(items, list):
            return
        changed = False
        for land in items:
            if not isinstance(land, dict) or code_key(land) != code:
                continue
            if _cycle_stamp(land, _MARKER) != published_at:
                continue
            extras = dict(land.get("extras") or {}) if isinstance(land.get("extras"), dict) else {}
            extras.pop(_MARKER, None)
            land["extras"] = extras
            land.pop(_MARKER, None)
            changed = True
        if changed:
            save_listings(items, app)


def maybe_send_quiet_listing_nudges(
    *,
    now: Optional[datetime] = None,
    sender: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    app=None,
) -> List[Dict[str, Any]]:
    """آگهی‌های ساکت را یک‌بار در هر چرخه پیامک کن. ارسال ناموفق نشانه را برمی‌دارد."""
    if not quiet_nudge_enabled():
        return []
    ref = now or utcnow()
    if ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    send = sender or _default_sender
    sent: List[Dict[str, Any]] = []
    try:
        items = _read_json(listings_path(app))
    except Exception:
        return []
    if not isinstance(items, list):
        return []
    visits = load_visit_rows(app)
    seen: set[str] = set()
    for land in items:
        if not isinstance(land, dict):
            continue
        code = code_key(land)
        published_at = _cycle_stamp(land, "published_at")
        if not code or not published_at or code in seen:
            continue
        if not _due(land, ref, visits):
            continue
        seen.add(code)
        claimed = _claim(code, published_at, ref, app)
        if not claimed:
            continue
        try:
            result = send(claimed["phone"], claimed["message"]) or {}
            ok = bool(result.get("ok"))
        except Exception:
            ok = False
            result = {"ok": False}
        if not ok:
            _release(code, published_at, app)
            continue
        sent.append(
            {
                "code": code,
                "phone": claimed["phone"],
                "published_at": published_at,
                "message": claimed["message"],
                "result": result,
            }
        )
    return sent
