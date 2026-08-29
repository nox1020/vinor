"""Period bucketing for time-series analytics."""

from __future__ import annotations

from datetime import date

import jdatetime

from app.config import CALENDAR_JALALI
from app.utils.dates import parse_iso_date, period_key


def bucket_key(iso_date: str, period: str, calendar: str) -> str:
    """
    Period types: daily, weekly, monthly, quarterly, semi_annual, yearly, all.
    """
    if period == "all":
        return "all"
    if period in ("daily", "monthly", "yearly"):
        return period_key(iso_date, period, calendar)

    d = parse_iso_date(iso_date)
    if period == "weekly":
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    if calendar == CALENDAR_JALALI:
        j = jdatetime.date.fromgregorian(date=d)
        if period == "quarterly":
            q = (j.month - 1) // 3 + 1
            return f"{j.year:04d}-Q{q}"
        if period == "semi_annual":
            h = 1 if j.month <= 6 else 2
            return f"{j.year:04d}-H{h}"
    else:
        if period == "quarterly":
            q = (d.month - 1) // 3 + 1
            return f"{d.year:04d}-Q{q}"
        if period == "semi_annual":
            h = 1 if d.month <= 6 else 2
            return f"{d.year:04d}-H{h}"

    return period_key(iso_date, "daily", calendar)


PERIOD_TYPES = (
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "semi_annual",
    "yearly",
    "all",
)
