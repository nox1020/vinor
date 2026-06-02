"""ثبت خودکار تیک‌های روتین روزانه همکار (آمارگیر — بدون ورود دستی)."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Sequence

from ..utils.storage import load_partner_routines_cached, save_partner_routines

ROUTINE_STEP_MARKETING = "1"  # بازاریابی — آنلاین شدن / فعالیت در پنل
ROUTINE_STEP_VISIT = "2"      # بازدید — مشاهده یا اقدام روی جزئیات فایل
ROUTINE_STEP_DEAL = "3"       # معامله — ثبت درخواست معامله از جزئیات فایل

_VALID = frozenset({ROUTINE_STEP_MARKETING, ROUTINE_STEP_VISIT, ROUTINE_STEP_DEAL})


def _normalize_step_ids(step_ids: Iterable[str]) -> List[str]:
    out: List[str] = []
    for raw in step_ids:
        s = str(raw or "").strip()
        if s in _VALID and s not in out:
            out.append(s)
    return sorted(out, key=int)


def merge_routine_steps_for_phone(
    phone: str,
    *step_ids: str,
    day: str | None = None,
) -> bool:
    """
    ادغام تیک‌های خودکار برای یک روز (پیش‌فرض: امروز).
    بازگشت True اگر رکورد تغییر کرده باشد.
    """
    ph = (phone or "").strip()
    if not ph or not step_ids:
        return False

    add = _normalize_step_ids(step_ids)
    if not add:
        return False

    target_day = (day or "").strip() or datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(target_day, "%Y-%m-%d")
    except ValueError:
        target_day = datetime.now().strftime("%Y-%m-%d")

    records = load_partner_routines_cached() or []
    rec = next((r for r in records if str(r.get("phone") or "").strip() == ph), None)
    if not rec:
        rec = {
            "phone": ph,
            "days": [],
            "steps": {},
            "steps_detail": {},
            "updated_at": None,
        }
        records.append(rec)

    rec.setdefault("days", [])
    rec.setdefault("steps", {})
    rec.setdefault("steps_detail", {})

    detail_map = rec.get("steps_detail")
    if not isinstance(detail_map, dict):
        detail_map = {}
        rec["steps_detail"] = detail_map

    current = detail_map.get(target_day)
    if not isinstance(current, list):
        current = []
    merged = _normalize_step_ids(list(current) + add)
    if merged == _normalize_step_ids(current):
        return False

    detail_map[target_day] = merged
    count = len(merged)
    steps_map = rec.get("steps")
    if not isinstance(steps_map, dict):
        steps_map = {}
        rec["steps"] = steps_map
    steps_map[target_day] = count

    if count > 0 and target_day not in rec["days"]:
        rec["days"] = sorted(set(rec.get("days") or []) | {target_day})
    elif count == 0 and target_day in (rec.get("days") or []):
        rec["days"] = [d for d in rec["days"] if d != target_day]

    rec["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_partner_routines(records)
    return True


def routine_detail_for_phone(phone: str, day: str | None = None) -> List[str]:
    ph = (phone or "").strip()
    if not ph:
        return []
    target_day = (day or "").strip() or datetime.now().strftime("%Y-%m-%d")
    records = load_partner_routines_cached() or []
    rec = next((r for r in records if str(r.get("phone") or "").strip() == ph), None)
    if not rec or not isinstance(rec.get("steps_detail"), dict):
        return []
    raw = rec["steps_detail"].get(target_day)
    if not isinstance(raw, list):
        return []
    return _normalize_step_ids(raw)
