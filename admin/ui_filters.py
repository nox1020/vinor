# -*- coding: utf-8 -*-
"""Small presentation filters for the admin panel (Persian digits, Tehran time)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .blueprint import admin_bp

TEHRAN = timezone(timedelta(hours=3, minutes=30))
JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(value: Any) -> str:
    return str(value).translate(_FA)


def parse_any_dt(value: Any) -> Optional[datetime]:
    """ISO string (with or without Z/offset), epoch seconds/ms, or datetime → aware UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.isdigit():
            return parse_any_dt(int(raw))
        raw = raw.replace(" ", "T", 1).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            try:
                dt = datetime.strptime(raw[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@admin_bp.app_template_filter("admin_dt")
def admin_dt(value: Any, with_time: bool = True) -> str:
    """«۵ آذر ۱۴۰۵، ۱۷:۲۰» in Tehran time; returns «—» when unparsable."""
    dt = parse_any_dt(value)
    if dt is None:
        return "—"
    from app.utils.dates import gregorian_to_jalali

    local = dt.astimezone(TEHRAN)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    out = f"{jd} {JALALI_MONTHS[jm - 1]} {jy}"
    if with_time:
        out += f"، {local:%H:%M}"
    return _fa(out)


@admin_bp.app_template_filter("admin_ago")
def admin_ago(value: Any) -> str:
    """Short Persian relative time («۳ ساعت پیش»), falling back to the date after a week."""
    dt = parse_any_dt(value)
    if dt is None:
        return "—"
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 0:
        return admin_dt(value)
    if secs < 60:
        return "همین حالا"
    if secs < 3600:
        return _fa(f"{secs // 60} دقیقه پیش")
    if secs < 86400:
        return _fa(f"{secs // 3600} ساعت پیش")
    if secs < 7 * 86400:
        days = secs // 86400
        return "دیروز" if days == 1 else _fa(f"{days} روز پیش")
    return admin_dt(value, with_time=False)


@admin_bp.app_template_filter("fa_num")
def fa_num(value: Any) -> str:
    """Grouped Persian number: 12500 → «۱۲٬۵۰۰»."""
    try:
        num = int(float(str(value).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return _fa(value if value is not None else "")
    return _fa(f"{num:,}").replace(",", "٬")
