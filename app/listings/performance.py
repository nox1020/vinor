# -*- coding: utf-8 -*-
"""آمار واقعی یک آگهی از زمان published_at.

بازدیدها همان ردیف‌های express_partner_views.json هستند (یک IP برای هر آگهی
در هر روز). درخواست بازدید از express_visit_requests.json خوانده می‌شود.
هیچ عدد بازاری ساخته نمی‌شود.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app.listings.service import _cycle_stamp, code_key
from app.utils.dates import parse_iso_to_naive_utc, utcnow

_WEEK = timedelta(days=7)


def parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_iso_to_naive_utc(text)
    if parsed is not None:
        return parsed
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if " " in text else text[:10], fmt)
        except (TypeError, ValueError):
            continue
    return None


def load_view_rows(app=None) -> List[dict]:
    try:
        from app.utils.storage import load_express_partner_views

        rows = load_express_partner_views(app) or []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []


def load_visit_rows(app=None) -> List[dict]:
    try:
        from app.utils.storage import load_express_visit_requests

        rows = load_express_visit_requests(app) or []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []


def _same_code(row_code: Any, code: str) -> bool:
    return code_key({"code": row_code}) == code and bool(code)


def _unique_viewers(
    views: Iterable[dict],
    code: str,
    *,
    start: datetime,
    end: Optional[datetime] = None,
) -> int:
    seen: set[str] = set()
    for row in views:
        if not _same_code(row.get("code"), code):
            continue
        when = parse_ts(row.get("timestamp") or row.get("created_at"))
        if when is None or when < start:
            continue
        if end is not None and when >= end:
            continue
        ip = str(row.get("ip") or "").strip()
        if not ip:
            continue
        seen.add(ip)
    return len(seen)


def _visit_count(
    visits: Iterable[dict],
    code: str,
    *,
    start: datetime,
    end: Optional[datetime] = None,
) -> int:
    total = 0
    for row in visits:
        if not _same_code(row.get("land_code") or row.get("code"), code):
            continue
        when = parse_ts(row.get("created_at") or row.get("timestamp"))
        if when is None or when < start:
            continue
        if end is not None and when >= end:
            continue
        total += 1
    return total


def listing_performance(
    land: Dict[str, Any] | None,
    *,
    now: Optional[datetime] = None,
    views: Optional[List[dict]] = None,
    visits: Optional[List[dict]] = None,
    app=None,
) -> Dict[str, Any]:
    """آمار از published_at همین چرخه. بدون تاریخ انتشار، شمارنده‌ها صفر و تاریخ‌ها null."""
    empty = {
        "weekly_views": 0,
        "views_since_publish": 0,
        "visit_requests_7d": 0,
        "visit_requests_total": 0,
        "published_at": None,
        "first_published_at": None,
        "days_since_publish": None,
    }
    if not isinstance(land, dict):
        return dict(empty)
    published_at = _cycle_stamp(land, "published_at") or None
    first = _cycle_stamp(land, "first_published_at") or None
    empty["published_at"] = published_at
    empty["first_published_at"] = first
    start = parse_ts(published_at) if published_at else None
    if start is None:
        return empty
    ref = now or utcnow()
    if ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    code = code_key(land)
    view_rows = load_view_rows(app) if views is None else views
    visit_rows = load_visit_rows(app) if visits is None else visits
    week_start = max(start, ref - _WEEK)
    empty["views_since_publish"] = _unique_viewers(view_rows, code, start=start)
    empty["weekly_views"] = _unique_viewers(view_rows, code, start=week_start)
    empty["visit_requests_total"] = _visit_count(visit_rows, code, start=start)
    empty["visit_requests_7d"] = _visit_count(visit_rows, code, start=week_start)
    elapsed = ref - start
    empty["days_since_publish"] = max(0, int(elapsed.total_seconds() // 86400))
    return empty


def publish_to_visit_7d_kpi(
    *,
    listings: Optional[List[Any]] = None,
    visits: Optional[List[dict]] = None,
    now: Optional[datetime] = None,
    limit: int = 5000,
    app=None,
) -> Dict[str, Any]:
    """سهم آگهی‌هایی که دست‌کم یک درخواست بازدید در ۷ روز پس از published_at دارند.

    فقط چرخه‌هایی که ۷ روزشان کامل شده در مخرج می‌آیند.
    """
    out = {
        "publish_to_visit_7d_rate": 0.0,
        "published_measured_count": 0,
        "published_with_visit_7d_count": 0,
    }
    try:
        if listings is None:
            from app.listings.service import _read_json, listings_path

            raw = _read_json(listings_path(app))
            listings = raw if isinstance(raw, list) else []
        if visits is None:
            visits = load_visit_rows(app)
        ref = now or utcnow()
        if ref.tzinfo is not None:
            ref = ref.replace(tzinfo=None)
        measured = 0
        hits = 0
        seen: set[str] = set()
        for land in listings[:limit]:
            if not isinstance(land, dict):
                continue
            code = code_key(land)
            if not code or code in seen:
                continue
            start = parse_ts(_cycle_stamp(land, "published_at"))
            if start is None or ref < start + _WEEK:
                continue
            seen.add(code)
            measured += 1
            if _visit_count(visits, code, start=start, end=start + _WEEK) > 0:
                hits += 1
        out["published_measured_count"] = measured
        out["published_with_visit_7d_count"] = hits
        out["publish_to_visit_7d_rate"] = round(hits / measured, 4) if measured else 0.0
    except Exception:
        return {
            "publish_to_visit_7d_rate": 0.0,
            "published_measured_count": 0,
            "published_with_visit_7d_count": 0,
        }
    return out
