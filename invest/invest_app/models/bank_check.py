# -*- coding: utf-8 -*-
"""یک چک دریافتی یا پرداختی در دفتر شخصی."""
from __future__ import annotations

from typing import Any

DIRECTION_RECEIVABLE = "receivable"
DIRECTION_PAYABLE = "payable"
DIRECTIONS = frozenset({DIRECTION_RECEIVABLE, DIRECTION_PAYABLE})

STATUS_PENDING = "pending"
STATUS_CLEARED = "cleared"
STATUS_BOUNCED = "bounced"
STATUS_ENDORSED = "endorsed"
STATUS_CANCELLED = "cancelled"
STATUSES = frozenset({
    STATUS_PENDING,
    STATUS_CLEARED,
    STATUS_BOUNCED,
    STATUS_ENDORSED,
    STATUS_CANCELLED,
})
OPEN_STATUSES = frozenset({STATUS_PENDING, STATUS_BOUNCED})

# همان دکمه‌های اپ: نزد صندوق همهٔ وضعیت‌ها، برگشتی بدون خرج‌کردن،
# و وصول‌شده / خرج‌شده / باطل فقط بازگشت به جریان. ماندن روی وضعیت یعنی ویرایش.
TRANSITIONS = {
    STATUS_PENDING: frozenset({
        STATUS_PENDING, STATUS_CLEARED, STATUS_BOUNCED, STATUS_ENDORSED, STATUS_CANCELLED,
    }),
    STATUS_BOUNCED: frozenset({
        STATUS_BOUNCED, STATUS_PENDING, STATUS_CLEARED, STATUS_CANCELLED,
    }),
    STATUS_CLEARED: frozenset({STATUS_CLEARED, STATUS_PENDING}),
    STATUS_ENDORSED: frozenset({STATUS_ENDORSED, STATUS_PENDING}),
    STATUS_CANCELLED: frozenset({STATUS_CANCELLED, STATUS_PENDING}),
}

CHECKS_SYNCED_KEY = "client_checks_synced"


def direction_label(direction: str) -> str:
    return "دریافتی" if direction == DIRECTION_RECEIVABLE else "پرداختی"


def status_label(direction: str, status: str) -> str:
    if status == STATUS_PENDING:
        return "نزد صندوق" if direction == DIRECTION_RECEIVABLE else "صادر شده"
    if status == STATUS_CLEARED:
        return "وصول شده" if direction == DIRECTION_RECEIVABLE else "پاس شده"
    if status == STATUS_BOUNCED:
        return "برگشتی"
    if status == STATUS_ENDORSED:
        return "خرج شده"
    if status == STATUS_CANCELLED:
        return "باطل"
    return status


def due_label(days: int) -> str:
    if days < 0:
        n = -days
        return "دیروز سررسید شد" if n == 1 else f"{n} روز از سررسید گذشته"
    if days == 0:
        return "سررسید امروز"
    if days == 1:
        return "سررسید فردا"
    return f"{days} روز تا سررسید"


def json_amount(value: float) -> int | float:
    rounded = round(float(value))
    if abs(float(value) - rounded) < 1e-6:
        return int(rounded)
    return round(float(value), 2)


def row_to_public(row: dict[str, Any], *, today) -> dict[str, Any]:
    """پاسخ JSON. تاریخ ذخیره میلادی است و کنارش شمسی هم می‌آید."""
    from invest_app.utils.dates import format_short_date, parse_iso_date
    from invest_app.config import CALENDAR_JALALI

    direction = str(row.get("direction") or "")
    status = str(row.get("status") or "")
    due = str(row.get("due_date") or "")
    issue = str(row.get("issue_date") or "")
    settled = str(row.get("settled_date") or "").strip()
    try:
        days = (parse_iso_date(due) - today).days
    except Exception:
        days = 0
    amount = json_amount(float(row.get("amount") or 0))
    open_row = status in OPEN_STATUSES
    archived_at = str(row.get("archived_at") or "").strip() or None
    live = archived_at is None
    return {
        "id": int(row["id"]),
        "direction": direction,
        "direction_label": direction_label(direction),
        "amount": amount,
        "issue_date": issue,
        "issue_date_jalali": format_short_date(issue, CALENDAR_JALALI),
        "due_date": due,
        "due_date_jalali": format_short_date(due, CALENDAR_JALALI),
        "check_number": str(row.get("check_number") or ""),
        "sayad_id": str(row.get("sayad_id") or ""),
        "bank_name": str(row.get("bank_name") or ""),
        "branch": str(row.get("branch") or ""),
        "counterparty": str(row.get("counterparty") or ""),
        "purpose": str(row.get("purpose") or ""),
        "note": str(row.get("note") or ""),
        "status": status,
        "status_label": status_label(direction, status),
        "settled_date": settled or None,
        "settled_date_jalali": format_short_date(settled, CALENDAR_JALALI) if settled else None,
        "is_open": open_row,
        "archived_at": archived_at,
        "is_archived": not live,
        "counts_as_receivable": live and direction == DIRECTION_RECEIVABLE and status == STATUS_PENDING,
        "counts_as_debt": live and direction == DIRECTION_PAYABLE and status in OPEN_STATUSES,
        "days_until_due": days,
        "due_label": due_label(days),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }
