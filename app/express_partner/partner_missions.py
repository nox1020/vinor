# -*- coding: utf-8 -*-
"""مأموریت رندوم همکار اکسپرس — تخصیص فایل + بذر چت AI تا معامله نهایی."""
from __future__ import annotations

import os
import random
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import current_app

from ..utils.dates import is_ad_expired
from ..utils.storage import (
    data_dir,
    load_express_assignments,
    load_express_lands_cached,
    load_partner_missions,
    save_express_assignments,
    save_partner_missions,
)

_LOCK_NAME = "partner_mission_assign.run.lock"
_STATUS_ACTIVE = "active"
_STATUS_DONE = "done"
_STATUS_ABANDONED = "abandoned"


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _norm_phone(phone: str) -> str:
    try:
        from ..services.sms import normalize_iran_mobile

        return normalize_iran_mobile(str(phone or "").strip()) or str(phone or "").strip()
    except Exception:
        return str(phone or "").strip()


def _try_acquire_lock():
    try:
        lock_path = os.path.join(data_dir(current_app), _LOCK_NAME)
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        return fd
    except FileExistsError:
        try:
            lock_path = os.path.join(data_dir(current_app), _LOCK_NAME)
            age = time.time() - os.path.getmtime(lock_path)
            if age > 120:
                os.remove(lock_path)
                return _try_acquire_lock()
        except Exception:
            pass
        return None
    except Exception:
        return None


def _release_lock(fd) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        lock_path = os.path.join(data_dir(current_app), _LOCK_NAME)
        if os.path.isfile(lock_path):
            os.remove(lock_path)
    except Exception:
        pass


def _missions_list() -> List[Dict[str, Any]]:
    rows = load_partner_missions() or []
    return [r for r in rows if isinstance(r, dict)]


def get_active_mission(phone: str) -> Optional[Dict[str, Any]]:
    ph = _norm_phone(phone)
    if not ph:
        return None
    for row in _missions_list():
        if str(row.get("partner_phone") or "").strip() != ph:
            continue
        if str(row.get("status") or "").strip().lower() != _STATUS_ACTIVE:
            continue
        return dict(row)
    return None


def _land_by_code(code: str) -> Optional[Dict[str, Any]]:
    code_s = str(code or "").strip()
    if not code_s:
        return None
    for land in load_express_lands_cached() or []:
        if not isinstance(land, dict):
            continue
        if str(land.get("code") or "").strip() == code_s:
            return land
    return None


def _land_is_open(land: Dict[str, Any] | None) -> bool:
    if not isinstance(land, dict):
        return False
    if str(land.get("express_status") or "").strip().lower() == "sold":
        return False
    try:
        if is_ad_expired(land):
            return False
    except Exception:
        pass
    return True


def complete_mission(
    phone: str,
    *,
    land_code: str | None = None,
    status: str = _STATUS_DONE,
) -> Optional[Dict[str, Any]]:
    ph = _norm_phone(phone)
    if not ph:
        return None
    want_code = str(land_code or "").strip()
    rows = _missions_list()
    changed = False
    done_row: Optional[Dict[str, Any]] = None
    for row in rows:
        if str(row.get("partner_phone") or "").strip() != ph:
            continue
        if str(row.get("status") or "").strip().lower() != _STATUS_ACTIVE:
            continue
        code = str(row.get("land_code") or "").strip()
        if want_code and code != want_code:
            continue
        row["status"] = status
        row["completed_at"] = _now_iso()
        changed = True
        done_row = dict(row)
        break
    if changed:
        save_partner_missions(rows)
    return done_row


def refresh_mission_if_land_closed(phone: str) -> Optional[Dict[str, Any]]:
    """اگر فایل مأموریت sold/منقضی شد → mission را done کن و None برگردان."""
    mission = get_active_mission(phone)
    if not mission:
        return None
    code = str(mission.get("land_code") or "").strip()
    land = _land_by_code(code)
    if not _land_is_open(land):
        complete_mission(phone, land_code=code, status=_STATUS_DONE)
        return None
    # assignment شخصی sold؟
    ph = _norm_phone(phone)
    for a in load_express_assignments() or []:
        if not isinstance(a, dict):
            continue
        if str(a.get("partner_phone") or "").strip() != ph:
            continue
        if str(a.get("land_code") or "").strip() != code:
            continue
        if str(a.get("status") or "").strip().lower() == "sold":
            complete_mission(phone, land_code=code, status=_STATUS_DONE)
            return None
        break
    return mission


def _assignment_counts() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for a in load_express_assignments() or []:
        if not isinstance(a, dict):
            continue
        st = str(a.get("status") or "").strip().lower()
        if st == "sold":
            continue
        code = str(a.get("land_code") or "").strip()
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
    return counts


def _pick_random_open_land(phone: str) -> Optional[Dict[str, Any]]:
    """فایل باز اکسپرس؛ ترجیح کم‌تخصیص‌یافته؛ ترجیحاً فایلی که قبلاً مأموریت همین همکار نبوده."""
    ph = _norm_phone(phone)
    past_codes = {
        str(r.get("land_code") or "").strip()
        for r in _missions_list()
        if str(r.get("partner_phone") or "").strip() == ph
        and str(r.get("land_code") or "").strip()
    }
    counts = _assignment_counts()
    open_lands: List[Dict[str, Any]] = []
    for land in load_express_lands_cached() or []:
        if not isinstance(land, dict):
            continue
        if not _land_is_open(land):
            continue
        code = str(land.get("code") or "").strip()
        if not code:
            continue
        open_lands.append(land)
    if not open_lands:
        return None

    fresh = [l for l in open_lands if str(l.get("code") or "").strip() not in past_codes]
    pool = fresh or open_lands

    def sort_key(land: Dict[str, Any]):
        code = str(land.get("code") or "").strip()
        return (counts.get(code, 0), random.random())

    pool_sorted = sorted(pool, key=sort_key)
    # از بین ۱۰ کم‌تخصیص‌شده یکی را رندوم بردار
    top = pool_sorted[: max(1, min(10, len(pool_sorted)))]
    return random.choice(top)


def _ensure_personal_assignment(phone: str, land: Dict[str, Any]) -> None:
    ph = _norm_phone(phone)
    code = str(land.get("code") or "").strip()
    if not ph or not code:
        return
    items = load_express_assignments() or []
    if not isinstance(items, list):
        items = []
    for a in items:
        if not isinstance(a, dict):
            continue
        if str(a.get("partner_phone") or "").strip() != ph:
            continue
        if str(a.get("land_code") or "").strip() != code:
            continue
        # موجود است
        return
    try:
        from .new_land_sms import resolve_express_land_commission_pct

        pct = float(resolve_express_land_commission_pct(land) or 0)
    except Exception:
        pct = float(land.get("express_commission_pct") or land.get("commission_pct") or 0)
    max_id = max(
        [int(x.get("id", 0) or 0) for x in items if isinstance(x, dict)],
        default=0,
    )
    items.append(
        {
            "id": max_id + 1,
            "partner_phone": ph,
            "land_code": code,
            "commission_pct": pct,
            "status": "active",
            "created_at": _now_iso(),
            "source": "random_mission",
        }
    )
    save_express_assignments(items)


def _seed_mission_chat(phone: str, land: Dict[str, Any]) -> str:
    """ترد جدید + پیام کاربر مأموریت + پاسخ آماده (متن آگهی)."""
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import (
        append_exchange,
        create_thread,
        load_user_record,
        set_active_thread,
        _find_thread,
        _save_record,
    )
    from .sales_coach import build_coach_chat_prompt, draft_listing_copy

    ph = _norm_phone(phone)
    code = str(land.get("code") or "").strip()
    title = str(land.get("title") or "").strip()
    tid = create_thread(ph, activate=True, audience=AUDIENCE_PARTNER)

    # عنوان صریح مأموریت
    try:
        record = load_user_record(ph, AUDIENCE_PARTNER)
        th = _find_thread(record, tid)
        if th:
            th["title"] = f"ماموریت {code}" if code else "ماموریت فروش"
            _save_record(record, ph, AUDIENCE_PARTNER)
    except Exception:
        pass

    user_msg = build_coach_chat_prompt(code=code, title=title, stage_label="علاقه‌مند")
    copies = draft_listing_copy(land, channel="both")
    divar = str(copies.get("divar") or "").strip()
    # بذر کوتاه و ماموریت‌محور؛ متن کامل فقط با درخواست بعدی
    title_bit = f" — {title}" if title else ""
    assistant_msg = (
        f"ماموریت فعال: فایل {code}{title_bit}.\n"
        f"کار بعدی: همین امروز آگهی دیوار بگذار و استوری اینستا بزن.\n"
        f"متن آماده است — بنویس «متن دیوار» یا «کپشن اینستا» تا کامل بفرستم."
    )
    if divar:
        # یک خط خلاصه از عنوان دیوار
        first_line = divar.split("\n", 1)[0].strip()
        if first_line:
            assistant_msg += f"\nخلاصه: {first_line[:90]}"
    append_exchange(
        ph,
        user_msg,
        assistant_msg,
        thread_id=tid,
        audience=AUDIENCE_PARTNER,
    )
    set_active_thread(ph, tid, audience=AUDIENCE_PARTNER)
    return tid


def ensure_random_mission(phone: str) -> Optional[Dict[str, Any]]:
    """
    اگر مأموریت فعال باز باشد همان را برگردان (و در صورت sold کامل کن).
    وگرنه یک فایل رندوم اختصاص بده، assignment بنویس، چت بذر بزن.
    """
    ph = _norm_phone(phone)
    if not ph:
        return None

    existing = refresh_mission_if_land_closed(ph)
    if existing:
        return existing

    fd = _try_acquire_lock()
    if fd is None:
        # همزمان؛ دوباره فقط active را بخوان
        time.sleep(0.05)
        return get_active_mission(ph)

    try:
        # دوباره چک زیر قفل
        existing = refresh_mission_if_land_closed(ph)
        if existing:
            return existing

        land = _pick_random_open_land(ph)
        if not land:
            return None

        code = str(land.get("code") or "").strip()
        _ensure_personal_assignment(ph, land)

        thread_id = ""
        try:
            thread_id = _seed_mission_chat(ph, land)
        except Exception:
            current_app.logger.exception(
                "mission chat seed failed phone=%s code=%s", ph, code
            )

        mid = str(uuid.uuid4())
        row = {
            "id": mid,
            "partner_phone": ph,
            "land_code": code,
            "status": _STATUS_ACTIVE,
            "thread_id": thread_id,
            "assigned_at": _now_iso(),
            "source": "random_home",
            "last_followup_at": "",
        }
        rows = _missions_list()
        rows.append(row)
        save_partner_missions(rows)
        return dict(row)
    except Exception:
        current_app.logger.exception("ensure_random_mission failed phone=%s", ph)
        return None
    finally:
        _release_lock(fd)


def mark_mission_followup(phone: str, land_code: str) -> None:
    ph = _norm_phone(phone)
    code = str(land_code or "").strip()
    if not ph or not code:
        return
    rows = _missions_list()
    changed = False
    for row in rows:
        if str(row.get("partner_phone") or "").strip() != ph:
            continue
        if str(row.get("land_code") or "").strip() != code:
            continue
        if str(row.get("status") or "").strip().lower() != _STATUS_ACTIVE:
            continue
        row["last_followup_at"] = _now_iso()
        changed = True
        break
    if changed:
        save_partner_missions(rows)


def append_mission_chat_followup(
    phone: str,
    *,
    land_code: str,
    thread_id: str,
    body: str,
) -> bool:
    """پیام کوتاه مربی داخل ترد مأموریت (بدون پیام کاربر)."""
    text = (body or "").strip()
    tid = (thread_id or "").strip()
    if not text or not tid:
        return False
    try:
        from app.ai.audience import AUDIENCE_PARTNER
        from app.ai.chat_store import append_exchange

        append_exchange(
            _norm_phone(phone),
            "",
            text,
            thread_id=tid,
            audience=AUDIENCE_PARTNER,
        )
        mark_mission_followup(phone, land_code)
        return True
    except Exception:
        current_app.logger.exception(
            "mission chat followup failed phone=%s code=%s", phone, land_code
        )
        return False
