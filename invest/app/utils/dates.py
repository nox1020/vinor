"""Date formatting and conversion (Gregorian storage, Jalali/Gregorian display)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import jdatetime

from app.config import CALENDAR_GREGORIAN, CALENDAR_JALALI

_JALALI_MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def parse_iso_date(value: str) -> date:
    if not value:
        return date.today()
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value[:10])


def iter_dates(start: date | str, end: date | str):
    """Yield each calendar date from start to end inclusive."""
    from datetime import timedelta

    d0 = start if isinstance(start, date) else parse_iso_date(str(start))
    d1 = end if isinstance(end, date) else parse_iso_date(str(end))
    if d1 < d0:
        d0, d1 = d1, d0
    cur = d0
    while cur <= d1:
        yield cur
        cur = cur + timedelta(days=1)


def format_display_date(value: str | date | None, calendar: str) -> str:
    """Format a stored ISO date for UI display."""
    if value is None or value == "":
        return "—"
    d = value if isinstance(value, date) else parse_iso_date(str(value))
    if calendar == CALENDAR_JALALI:
        j = jdatetime.date.fromgregorian(date=d)
        return f"{j.day:02d} {_JALALI_MONTHS[j.month - 1]} {j.year}"
    return d.strftime("%Y-%m-%d")


def format_short_date(value: str | date | None, calendar: str) -> str:
    if value is None or value == "":
        return "—"
    d = value if isinstance(value, date) else parse_iso_date(str(value))
    if calendar == CALENDAR_JALALI:
        j = jdatetime.date.fromgregorian(date=d)
        return f"{j.year}/{j.month:02d}/{j.day:02d}"
    return d.strftime("%Y-%m-%d")


def format_month_label(value: str | date, calendar: str) -> str:
    d = value if isinstance(value, date) else parse_iso_date(str(value))
    if calendar == CALENDAR_JALALI:
        j = jdatetime.date.fromgregorian(date=d)
        return f"{_JALALI_MONTHS[j.month - 1]} {j.year}"
    return d.strftime("%b %Y")


def jalali_to_iso(year: int, month: int, day: int) -> str:
    g = jdatetime.date(year, month, day).togregorian()
    return g.isoformat()


def gregorian_parts(value: str | date | None = None) -> tuple[int, int, int]:
    d = date.today() if value is None else (
        value if isinstance(value, date) else parse_iso_date(str(value))
    )
    return d.year, d.month, d.day


def jalali_parts(value: str | date | None = None) -> tuple[int, int, int]:
    d = date.today() if value is None else (
        value if isinstance(value, date) else parse_iso_date(str(value))
    )
    j = jdatetime.date.fromgregorian(date=d)
    return j.year, j.month, j.day


def iso_from_parts(year: int, month: int, day: int, calendar: str) -> str:
    if calendar == CALENDAR_JALALI:
        return jalali_to_iso(year, month, day)
    return date(year, month, day).isoformat()


def period_key(value: str, period: str, calendar: str) -> str:
    """Group key for daily/monthly/yearly reports."""
    d = parse_iso_date(value)
    if calendar == CALENDAR_JALALI:
        j = jdatetime.date.fromgregorian(date=d)
        if period == "daily":
            return f"{j.year:04d}-{j.month:02d}-{j.day:02d}"
        if period == "monthly":
            return f"{j.year:04d}-{j.month:02d}"
        return f"{j.year:04d}"
    if period == "daily":
        return d.isoformat()
    if period == "monthly":
        return d.strftime("%Y-%m")
    return d.strftime("%Y")


# Re-export calendar constants for convenience
__all__ = [
    "today_iso",
    "now_iso",
    "parse_iso_date",
    "iter_dates",
    "format_display_date",
    "format_short_date",
    "format_month_label",
    "jalali_to_iso",
    "gregorian_parts",
    "jalali_parts",
    "iso_from_parts",
    "period_key",
    "CALENDAR_JALALI",
    "CALENDAR_GREGORIAN",
]
