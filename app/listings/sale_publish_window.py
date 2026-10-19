# -*- coding: utf-8 -*-
"""انتشار فروش ۳۰ روزه.

ساعت شروع، آخرین «انتشار فروش» است. اگر آن مهر نباشد، بهترین تاریخ واقعی
موجود (تأیید، بعد تاریخ ثبت) استفاده می‌شود. بعد از ۳۰ روز همان
``unpublish_owner_home`` که دکمهٔ «توقف انتشار فروش» صدا می‌زند اجرا می‌شود.
بایگانی جداست و اینجا عوض نمی‌شود.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.listings.performance import as_utc_naive, parse_ts
from app.listings.service import (
    _cycle_stamp,
    code_key,
    is_published_for_sale,
    listings_lock,
    listings_path,
    owner_phone,
    save_listings,
)
from app.listings.service import _read_json
from app.utils.dates import iso_z, utcnow

SALE_PUBLISH_DAYS = 30
SALE_PUBLISH_WINDOW = timedelta(days=SALE_PUBLISH_DAYS)
_LAZY_INTERVAL_SEC = 3600.0

# تازه‌ترین مهر انتشار اول است. updated_at ویرایش است و ساعت را عوض نمی‌کند.
_ANCHOR_KEYS = (
    "sale_published_at",
    "published_at",
    "first_published_at",
    "approved_at",
    "express_approved_at",
    "created_at",
)


def sale_publish_window_enabled() -> bool:
    raw = os.environ.get("VINOR_SALE_PUBLISH_WINDOW")
    if raw is None or not str(raw).strip():
        raw = "1"
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def sale_publish_anchor(land: Dict[str, Any] | None) -> Optional[datetime]:
    """بهترین تاریخ واقعی شروع همین انتشار فروش. تاریخ خراب نادیده گرفته می‌شود."""
    if not isinstance(land, dict):
        return None
    for key in _ANCHOR_KEYS:
        parsed = parse_ts(_cycle_stamp(land, key))
        if parsed is not None:
            return parsed
    return None


def _reference(now: Optional[datetime]) -> datetime:
    if now is None:
        return utcnow()
    return as_utc_naive(now)


def sale_publish_due(land: Dict[str, Any] | None, *, now: Optional[datetime] = None) -> bool:
    """انتشار فروشِ ذخیره‌شده ۳۰ روز یا بیشتر عمر دارد."""
    if not sale_publish_window_enabled() or not is_published_for_sale(land):
        return False
    anchor = sale_publish_anchor(land)
    if anchor is None:
        return False
    return _reference(now) >= anchor + SALE_PUBLISH_WINDOW


def sale_publish_expired(land: Dict[str, Any] | None, *, now: Optional[datetime] = None) -> bool:
    """فید عمومی: آگهیِ هنوز روشن که مهلتش گذشته، منتشر حساب نمی‌شود."""
    return sale_publish_due(land, now=now)


def sale_publish_fields(
    land: Dict[str, Any] | None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """فیلدهای افزودنی API. منتشرنشده هر دو را null می‌گذارد."""
    empty = {
        "sale_publish_expires_at": None,
        "sale_publish_remaining_seconds": None,
    }
    if not is_published_for_sale(land):
        return dict(empty)
    anchor = sale_publish_anchor(land)
    if anchor is None:
        return dict(empty)
    expires = anchor + SALE_PUBLISH_WINDOW
    remaining = int((expires - _reference(now)).total_seconds())
    if remaining < 0:
        remaining = 0
    return {
        "sale_publish_expires_at": iso_z(expires),
        "sale_publish_remaining_seconds": remaining,
    }


def _stamp_sale_clock(land: Dict[str, Any], stamp: str) -> bool:
    if _cycle_stamp(land, "sale_published_at") == stamp and stamp:
        return False
    extras = dict(land.get("extras") or {}) if isinstance(land.get("extras"), dict) else {}
    extras["sale_published_at"] = stamp
    land["extras"] = extras
    land["sale_published_at"] = stamp
    return True


def sweep_expired_sale_publishes(
    app=None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """توقف انتشارهای ۳۰روزه. تکرارش بی‌اثر است و هیچ ردیفی را پاک نمی‌کند.

    آگهی جوانِ بدون ``sale_published_at`` همان تاریخ واقعی را ذخیره می‌کند
    تا ساعت از نو شروع نشود. ``published_at`` دست نمی‌خورد تا آمار و یادآوری
    سکوت آگهی‌های قدیمی عوض نشود.
    """
    result: Dict[str, Any] = {
        "ok": True,
        "enabled": sale_publish_window_enabled(),
        "stopped": [],
        "backfilled": [],
        "kept": [],
        "skipped": [],
    }
    if not result["enabled"]:
        return result
    ref = _reference(now)
    pending: List[Tuple[str, str]] = []
    seen_stop: set[str] = set()
    seen_keep: set[str] = set()
    undated: List[str] = []
    with listings_lock(app):
        items = _read_json(listings_path(app))
        changed = False
        for land in items:
            if not isinstance(land, dict) or not is_published_for_sale(land):
                continue
            code = code_key(land)
            anchor = sale_publish_anchor(land)
            if not code or anchor is None:
                if code:
                    undated.append(code)
                continue
            if ref >= anchor + SALE_PUBLISH_WINDOW:
                if code not in seen_stop:
                    pending.append((code, owner_phone(land)))
                    seen_stop.add(code)
                continue
            if code not in seen_keep:
                result["kept"].append(code)
                seen_keep.add(code)
            if not _cycle_stamp(land, "sale_published_at"):
                if _stamp_sale_clock(land, iso_z(anchor)):
                    changed = True
                    if code not in result["backfilled"]:
                        result["backfilled"].append(code)
        if changed:
            save_listings(items, app)
    for code in undated:
        if code not in seen_stop and code not in seen_keep and code not in result["skipped"]:
            result["skipped"].append(code)
    from app.express_partner.special_listings import unpublish_owner_home

    for code, phone in pending:
        if not phone:
            result["skipped"].append(code)
            continue
        _rec, err = unpublish_owner_home(phone, land_code=code)
        if err:
            result["skipped"].append(code)
            continue
        result["stopped"].append(code)
    result["stopped_count"] = len(result["stopped"])
    return result


def install_sale_publish_sweep(app) -> None:
    """روی هر درخواست، حداکثر یک‌بار در ساعت. cron لازم نیست."""
    if not sale_publish_window_enabled():
        return
    try:
        from app.utils.lazy_scheduler import install_lazy_tick
    except Exception:
        return

    def _should_run() -> bool:
        try:
            from flask import current_app

            if current_app.testing or current_app.config.get("TESTING"):
                return False
        except Exception:
            return False
        return sale_publish_window_enabled()

    def _run() -> None:
        sweep_expired_sale_publishes()

    install_lazy_tick(
        app,
        name="sale-publish-window",
        should_run=_should_run,
        run=_run,
        min_interval_sec=_LAZY_INTERVAL_SEC,
    )


def main() -> int:
    """cPanel: ``python -m app.listings.sale_publish_window``."""
    import json

    from app import create_app

    application = create_app()
    with application.app_context():
        payload = sweep_expired_sale_publishes()
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
