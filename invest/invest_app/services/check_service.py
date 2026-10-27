# -*- coding: utf-8 -*-
"""اعتبارسنجی، تغییر وضعیت، و سررسید دفتر چک."""
from __future__ import annotations

import math
import sqlite3
from datetime import date
from typing import Any

from invest_app.models.bank_check import (
    CHECKS_SYNCED_KEY,
    DIRECTION_PAYABLE,
    DIRECTION_RECEIVABLE,
    DIRECTIONS,
    OPEN_STATUSES,
    STATUS_CANCELLED,
    STATUS_CLEARED,
    STATUS_ENDORSED,
    STATUS_PENDING,
    STATUSES,
    TRANSITIONS,
    json_amount,
    row_to_public,
)
from invest_app.repositories.check_repo import CheckRepository
from invest_app.utils.dates import jalali_to_iso, now_iso

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LIMITS = {
    "check_number": (32, "شماره چک"),
    "bank_name": (48, "نام بانک"),
    "branch": (48, "شعبه"),
    "counterparty": (80, "طرف حساب"),
    "purpose": (120, "بابت"),
    "note": (300, "یادداشت"),
    "endorsed_to": (80, "خرج شده به"),
    "endorsed_for": (120, "بابت خرج"),
}


class CheckError(ValueError):
    def __init__(self, message: str, *, code: str = "validation", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def tehran_today() -> date:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Tehran")).date()


def ascii_text(raw: Any) -> str:
    return str(raw or "").translate(_FA_DIGITS)


def parse_amount(raw: Any) -> float:
    if isinstance(raw, bool) or raw is None:
        raise CheckError("مبلغ چک باید بزرگ‌تر از صفر باشد.")
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = ascii_text(raw)
        for ch in (",", "٬", "،", " ", "\u00a0"):
            text = text.replace(ch, "")
        text = text.strip()
        if not text:
            raise CheckError("مبلغ چک باید بزرگ‌تر از صفر باشد.")
        try:
            value = float(text)
        except ValueError as exc:
            raise CheckError("مبلغ چک نامعتبر است.") from exc
    if math.isnan(value) or math.isinf(value) or value <= 0:
        raise CheckError("مبلغ چک باید بزرگ‌تر از صفر باشد.")
    if value > 1e16:
        raise CheckError("مبلغ چک نامعتبر است.")
    return value


def parse_calendar_date(raw: Any, *, label: str, required: bool = True) -> str:
    text = ascii_text(raw).strip()
    if not text:
        if required:
            raise CheckError(f"{label} الزامی است.")
        return ""
    text = text.replace("/", "-").replace(".", "-")
    if "T" in text:
        text = text.split("T", 1)[0]
    parts = [part for part in text.split("-") if part != ""]
    if len(parts) != 3:
        raise CheckError(f"{label} نامعتبر است.")
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as exc:
        raise CheckError(f"{label} نامعتبر است.") from exc
    try:
        if year >= 1700:
            return date(year, month, day).isoformat()
        if 1200 <= year <= 1699:
            return jalali_to_iso(year, month, day)
    except (ValueError, OverflowError) as exc:
        raise CheckError(f"{label} نامعتبر است.") from exc
    raise CheckError(f"{label} نامعتبر است.")


def _fold(raw: Any, key: str) -> str:
    text = str(raw or "")
    if key == "check_number":
        text = ascii_text(text)
    if key == "note":
        text = text.strip()
    else:
        text = " ".join(text.split())
    limit, label = _LIMITS[key]
    if len(text) > limit:
        raise CheckError(f"{label} طولانی است.")
    return text


def _sayad(raw: Any) -> str:
    return "".join(ch for ch in ascii_text(raw) if ch.isdigit())


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


class CheckService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._repo = CheckRepository(conn)

    def list_public(self, *, today: date | None = None) -> list[dict[str, Any]]:
        day = today or tehran_today()
        return [row_to_public(row, today=day) for row in self._repo.list_all()]

    def get_public(self, check_id: int, *, today: date | None = None) -> dict[str, Any]:
        row = self._repo.get(check_id)
        if row is None:
            raise CheckError("این چک پیدا نشد.", code="not_found", status=404)
        return row_to_public(row, today=today or tehran_today())

    def create(self, data: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
        day = today or tehran_today()
        prepared = self._prepare(data, current=None, today=day, enforce_transition=False)
        try:
            saved = self._repo.insert(prepared)
        except sqlite3.IntegrityError as exc:
            raise self._conflict_from_db(exc) from exc
        self.mark_synced()
        return row_to_public(saved, today=day)

    def update(self, check_id: int, data: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
        current = self._repo.get(check_id)
        if current is None:
            raise CheckError("این چک پیدا نشد.", code="not_found", status=404)
        day = today or tehran_today()
        merged = dict(current)
        merged.update(data or {})
        merged["id"] = check_id
        prepared = self._prepare(merged, current=current, today=day, enforce_transition=True)
        prepared["created_at"] = current["created_at"]
        try:
            saved = self._repo.update(check_id, prepared)
        except sqlite3.IntegrityError as exc:
            raise self._conflict_from_db(exc) from exc
        if saved is None:
            raise CheckError("این چک پیدا نشد.", code="not_found", status=404)
        self.mark_synced()
        return row_to_public(saved, today=day)

    def delete(self, check_id: int) -> None:
        if not self._repo.delete(check_id):
            raise CheckError("این چک پیدا نشد.", code="not_found", status=404)
        self.mark_synced()

    def replace_snapshot(self, items: list[Any], *, today: date | None = None) -> list[dict[str, Any]]:
        """جایگزینی کل دفتر از آینهٔ تنظیمات. شناسهٔ کلاینت حفظ می‌شود."""
        if not isinstance(items, list):
            raise CheckError("فهرست چک‌ها نامعتبر است.")
        day = today or tehran_today()
        prepared: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for raw in items:
            if not isinstance(raw, dict):
                raise CheckError("یکی از چک‌ها نامعتبر است.")
            row = self._prepare(
                raw,
                current=None,
                today=day,
                enforce_transition=False,
                others=prepared,
                against_db=False,
            )
            if row.get("id") is None:
                raise CheckError("شناسه چک برای همگام‌سازی الزامی است.")
            if row["id"] in seen_ids:
                raise CheckError("شناسه چک تکراری است.", code="conflict", status=409)
            seen_ids.add(row["id"])
            prepared.append(row)
        saved = self._repo.replace_all(prepared)
        self.mark_synced()
        return [row_to_public(row, today=day) for row in saved]

    def synced(self) -> bool:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (CHECKS_SYNCED_KEY,),
        ).fetchone()
        return bool(row and str(row["value"]).strip() == "1")

    def mark_synced(self) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (CHECKS_SYNCED_KEY, "1"),
        )
        self._conn.commit()

    def _prepare(
        self,
        data: dict[str, Any],
        *,
        current: dict[str, Any] | None,
        today: date,
        enforce_transition: bool,
        others: list[dict[str, Any]] | None = None,
        against_db: bool = True,
    ) -> dict[str, Any]:
        direction = str(_pick(data, "direction") or "").strip()
        if direction not in DIRECTIONS:
            raise CheckError("نوع چک را مشخص کنید: دریافتی یا پرداختی.")
        status = str(_pick(data, "status") or STATUS_PENDING).strip() or STATUS_PENDING
        if status not in STATUSES:
            raise CheckError("وضعیت چک نامعتبر است.")
        if direction == DIRECTION_PAYABLE and status == STATUS_ENDORSED:
            raise CheckError("چک پرداختی را نمی‌توان خرج‌شده ثبت کرد.")
        if enforce_transition and current is not None:
            previous = str(current.get("status") or STATUS_PENDING)
            allowed = TRANSITIONS.get(previous, frozenset({previous}))
            if status not in allowed:
                raise CheckError("این تغییر وضعیت مجاز نیست.")

        amount = parse_amount(_pick(data, "amount"))
        issue = parse_calendar_date(
            _pick(data, "issue_date", "issueDate", "issue_date_jalali"),
            label="تاریخ صدور",
        )
        due = parse_calendar_date(
            _pick(data, "due_date", "dueDate", "due_date_jalali"),
            label="تاریخ سررسید",
        )
        if due < issue:
            raise CheckError("سررسید نمی‌تواند قبل از تاریخ صدور باشد.")

        number = _fold(_pick(data, "check_number", "checkNumber", default=""), "check_number")
        sayad = _sayad(_pick(data, "sayad_id", "sayadId", default=""))
        if not number and not sayad:
            raise CheckError("شماره چک یا شناسه صیادی را وارد کنید.")
        if sayad and len(sayad) != 16:
            raise CheckError("شناسه صیادی باید ۱۶ رقم باشد.")

        bank = _fold(_pick(data, "bank_name", "bankName", default=""), "bank_name")
        branch = _fold(_pick(data, "branch", default=""), "branch")
        party = _fold(_pick(data, "counterparty", default=""), "counterparty")
        purpose = _fold(_pick(data, "purpose", default=""), "purpose")
        note = _fold(_pick(data, "note", default=""), "note")

        settled = None
        if status != STATUS_PENDING:
            raw_settled = _pick(data, "settled_date", "settledDate")
            if raw_settled:
                settled = parse_calendar_date(raw_settled, label="تاریخ تسویه")
            elif current and str(current.get("status") or "") == status and current.get("settled_date"):
                settled = str(current.get("settled_date"))
            else:
                settled = today.isoformat()

        check_id = _pick(data, "id")
        if check_id in ("", None):
            check_id = None
        else:
            try:
                check_id = int(check_id)
            except (TypeError, ValueError) as exc:
                raise CheckError("شناسه چک نامعتبر است.") from exc
            if check_id <= 0:
                raise CheckError("شناسه چک نامعتبر است.")

        self._ensure_unique(
            direction=direction,
            number=number,
            bank=bank,
            sayad=sayad,
            self_id=check_id,
            extra=others or [],
            against_db=against_db,
        )
        stamp = now_iso()
        created = str(_pick(data, "created_at", "createdAt") or "").strip() or stamp
        archived_at = _archived_value(data, current, stamp)
        endorsed_to = self._endorse_field(data, current, "endorsed_to", "endorsedTo")
        endorsed_for = self._endorse_field(data, current, "endorsed_for", "endorsedFor")
        return {
            "id": check_id,
            "direction": direction,
            "amount": amount,
            "issue_date": issue,
            "due_date": due,
            "check_number": number,
            "sayad_id": sayad,
            "bank_name": bank,
            "branch": branch,
            "counterparty": party,
            "purpose": purpose,
            "note": note,
            "status": status,
            "settled_date": settled,
            "archived_at": archived_at,
            "endorsed_to": endorsed_to,
            "endorsed_for": endorsed_for,
            "created_at": created,
            "updated_at": stamp,
        }

    @staticmethod
    def _endorse_field(data: dict[str, Any], current: dict[str, Any] | None, key: str, alt: str) -> str:
        """خرج‌شده به / بابت. نبودِ کلید یعنی همان مقدار قبلی (کلاینت قدیمی پاکش نمی‌کند)."""
        if key in data or alt in data:
            return _fold(_pick(data, key, alt, default=""), key)
        return str((current or {}).get(key) or "")

    def _ensure_unique(
        self,
        *,
        direction: str,
        number: str,
        bank: str,
        sayad: str,
        self_id: int | None,
        extra: list[dict[str, Any]],
        against_db: bool,
    ) -> None:
        rows: list[dict[str, Any]] = []
        if against_db:
            rows.extend(
                row for row in self._repo.list_all()
                if str(row.get("status")) != STATUS_CANCELLED
            )
        rows.extend(row for row in extra if str(row.get("status")) != STATUS_CANCELLED)
        for other in rows:
            other_id = other.get("id")
            if self_id is not None and other_id is not None and int(other_id) == int(self_id):
                continue
            if sayad and str(other.get("sayad_id") or "") == sayad:
                raise CheckError("این شناسه صیادی قبلاً ثبت شده است.", code="conflict", status=409)
            if (
                number
                and str(other.get("direction") or "") == direction
                and str(other.get("check_number") or "") == number
                and str(other.get("bank_name") or "") == bank
            ):
                raise CheckError("چکی با همین شماره و بانک قبلاً ثبت شده است.", code="conflict", status=409)

    def _conflict_from_db(self, exc: sqlite3.IntegrityError) -> CheckError:
        text = str(exc).lower()
        if "checks.id" in text:
            return CheckError("شناسه چک تکراری است.", code="conflict", status=409)
        if "sayad" in text:
            return CheckError("این شناسه صیادی قبلاً ثبت شده است.", code="conflict", status=409)
        return CheckError("چکی با همین شماره و بانک قبلاً ثبت شده است.", code="conflict", status=409)


def _archived_value(data: dict[str, Any], current: dict[str, Any] | None, stamp: str) -> str | None:
    """`archived` (bool) یا `archived_at` (متن). نبودِ هر دو یعنی همان مقدار قبلی."""
    previous = str((current or {}).get("archived_at") or "").strip() or None
    if "archived" in data or "isArchived" in data:
        flag = data.get("archived", data.get("isArchived"))
        if isinstance(flag, str):
            flag = flag.strip().lower() in ("1", "true", "yes")
        if not flag:
            return None
        explicit = str(_pick(data, "archived_at", "archivedAt") or "").strip()
        return explicit or previous or stamp
    if "archived_at" in data or "archivedAt" in data:
        return str(_pick(data, "archived_at", "archivedAt") or "").strip() or None
    return previous


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    open_receivable = 0
    open_receivable_count = 0
    debts = 0
    debt_count = 0
    bounced_receivable = 0
    bounced_receivable_count = 0
    bounced_payable = 0.0
    overdue_amount = 0
    overdue_count = 0
    due_soon_amount = 0
    due_soon_count = 0
    cleared_receivable = 0
    cleared_payable = 0.0
    next_due = None
    for item in items:
        if item.get("is_archived"):
            continue
        amount = float(item.get("amount") or 0)
        if item.get("counts_as_receivable"):
            open_receivable += amount
            open_receivable_count += 1
        if item.get("counts_as_debt"):
            debts += amount
            debt_count += 1
        if item.get("direction") == DIRECTION_RECEIVABLE and item.get("status") == "bounced":
            bounced_receivable += amount
            bounced_receivable_count += 1
        if item.get("direction") == DIRECTION_PAYABLE and item.get("status") == "bounced":
            bounced_payable += amount
        if item.get("direction") == DIRECTION_RECEIVABLE and item.get("status") == STATUS_CLEARED:
            cleared_receivable += amount
        if item.get("direction") == DIRECTION_PAYABLE and item.get("status") == STATUS_CLEARED:
            cleared_payable += amount
        if not item.get("is_open"):
            continue
        days = int(item.get("days_until_due") or 0)
        if days < 0:
            overdue_amount += amount
            overdue_count += 1
        elif days <= 7:
            due_soon_amount += amount
            due_soon_count += 1
        if next_due is None or str(item.get("due_date") or "") < str(next_due.get("due_date") or ""):
            next_due = item
    return {
        "open_receivable": json_amount(open_receivable),
        "open_receivable_count": open_receivable_count,
        "debts": json_amount(debts),
        "debt_count": debt_count,
        "bounced_receivable": json_amount(bounced_receivable),
        "bounced_receivable_count": bounced_receivable_count,
        "bounced_payable": json_amount(bounced_payable),
        "overdue_amount": json_amount(overdue_amount),
        "overdue_count": overdue_count,
        "due_soon_amount": json_amount(due_soon_amount),
        "due_soon_count": due_soon_count,
        "cleared_receivable": json_amount(cleared_receivable),
        "cleared_payable": json_amount(cleared_payable),
        "net": json_amount(open_receivable - debts),
        "next_due": next_due,
    }


def reminder_groups(items: list[dict[str, Any]], *, within_days: int = 7) -> dict[str, Any]:
    window = max(0, min(int(within_days), 60))
    overdue = []
    due_soon = []
    bounced = []
    for item in items:
        if item.get("is_archived"):
            continue
        if item.get("status") == "bounced":
            bounced.append(item)
        if item.get("status") not in OPEN_STATUSES:
            continue
        days = int(item.get("days_until_due") or 0)
        if days < 0:
            overdue.append(item)
        elif days <= window:
            due_soon.append(item)
    overdue.sort(key=lambda item: str(item.get("due_date") or ""))
    due_soon.sort(key=lambda item: str(item.get("due_date") or ""))
    return {
        "within_days": window,
        "overdue": overdue,
        "due_soon": due_soon,
        "bounced": bounced,
        "items": overdue + [item for item in due_soon if item not in overdue],
    }
