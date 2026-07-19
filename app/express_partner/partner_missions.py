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
        if _norm_phone(str(row.get("partner_phone") or "")) != ph:
            continue
        if str(row.get("status") or "").strip().lower() != _STATUS_ACTIVE:
            continue
        return dict(row)
    return None


def _latest_mission_for_land(phone: str, land_code: str) -> Optional[Dict[str, Any]]:
    """آخرین مأموریت همین همکار روی همین فایل (هر وضعیتی)."""
    ph = _norm_phone(phone)
    code = str(land_code or "").strip()
    if not ph or not code:
        return None
    matches: List[Dict[str, Any]] = []
    for row in _missions_list():
        if _norm_phone(str(row.get("partner_phone") or "")) != ph:
            continue
        if str(row.get("land_code") or "").strip() != code:
            continue
        matches.append(row)
    if not matches:
        return None

    def _sort_key(r: Dict[str, Any]):
        return str(r.get("assigned_at") or r.get("completed_at") or "")

    matches.sort(key=_sort_key)
    return dict(matches[-1])


def _find_existing_mission_thread(
    phone: str,
    land_code: str,
    *,
    preferred_tid: str = "",
) -> str:
    """ترد قبلی مأموریت همین فایل را پیدا کن — بدون ساختن ترد جدید."""
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import load_user_record, _find_thread

    ph = _norm_phone(phone)
    code = str(land_code or "").strip()
    prefer = str(preferred_tid or "").strip()
    try:
        record = load_user_record(ph, AUDIENCE_PARTNER)
    except Exception:
        return ""
    if not isinstance(record, dict):
        return ""
    if prefer and _find_thread(record, prefer):
        return prefer
    want_title = f"ماموریت {code}" if code else ""
    if not want_title:
        return ""
    threads = record.get("threads") or []
    if not isinstance(threads, list):
        return ""
    # جدیدترین هم‌عنوان
    found = ""
    for th in threads:
        if not isinstance(th, dict):
            continue
        if str(th.get("title") or "").strip() != want_title:
            continue
        tid = str(th.get("id") or "").strip()
        if tid:
            found = tid
    return found


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
        if _norm_phone(str(row.get("partner_phone") or "")) != ph:
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
        if _norm_phone(str(a.get("partner_phone") or "")) != ph:
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


def _pick_from_personal_assignments(phone: str) -> Optional[Dict[str, Any]]:
    """اگر همکار انتساب فعال روی فایل باز دارد، همان را برای مأموریت بردار."""
    ph = _norm_phone(phone)
    if not ph:
        return None
    open_by_code: Dict[str, Dict[str, Any]] = {}
    for land in load_express_lands_cached() or []:
        if not isinstance(land, dict) or not _land_is_open(land):
            continue
        code = str(land.get("code") or "").strip()
        if code:
            open_by_code[code] = land
    if not open_by_code:
        return None
    candidates: List[Dict[str, Any]] = []
    for a in load_express_assignments() or []:
        if not isinstance(a, dict):
            continue
        if _norm_phone(str(a.get("partner_phone") or "")) != ph:
            continue
        st = str(a.get("status") or "active").strip().lower()
        if st in ("sold", "closed", "cancelled", "canceled"):
            continue
        code = str(a.get("land_code") or "").strip()
        land = open_by_code.get(code)
        if land:
            candidates.append(land)
    if not candidates:
        return None
    return random.choice(candidates)


def _pick_random_open_land(phone: str) -> Optional[Dict[str, Any]]:
    """فایل باز اکسپرس؛ اول انتساب شخصی، بعد کم‌تخصیص‌یافته."""
    personal = _pick_from_personal_assignments(phone)
    if personal:
        return personal

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


def _ensure_personal_assignment(
    phone: str, land: Dict[str, Any], *, source: str = "random_mission"
) -> None:
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
            "source": (source or "random_mission").strip() or "random_mission",
        }
    )
    save_express_assignments(items)


def claim_express_land_for_partner(
    phone: str, land_code: str, *, source: str = "chat_claim"
) -> bool:
    """
    اختصاص شخصی فوری برای فایل اکسپرس باز — تا Visit/Deal از چت بدون انتساب قبلی کار کند.
    True اگر انتساب از قبل بود یا همین الان ساخته شد.
    """
    ph = _norm_phone(phone)
    code = str(land_code or "").strip()
    if not ph or not code:
        return False
    land = None
    for row in load_express_lands_cached() or []:
        if isinstance(row, dict) and str(row.get("code") or "").strip() == code:
            land = row
            break
    if land is None:
        return False
    # فایل فروخته‌شده را claim نکن
    st = str(land.get("status") or land.get("express_status") or "").strip().lower()
    if st in ("sold", "فروخته", "فروخته شده"):
        return False
    try:
        items = load_express_assignments() or []
        for a in items if isinstance(items, list) else []:
            if not isinstance(a, dict):
                continue
            if str(a.get("land_code") or "").strip() != code:
                continue
            aph = _norm_phone(str(a.get("partner_phone") or ""))
            ast = str(a.get("status") or "active").strip().lower()
            if aph and aph != ph and ast in ("in_transaction", "sold"):
                return False
    except Exception:
        pass
    _ensure_personal_assignment(ph, land, source=source)
    # تأیید وجود
    try:
        for a in load_express_assignments() or []:
            if not isinstance(a, dict):
                continue
            if _norm_phone(str(a.get("partner_phone") or "")) != ph:
                continue
            if str(a.get("land_code") or "").strip() != code:
                continue
            return True
    except Exception:
        return False
    return False


def _seed_mission_chat(
    phone: str,
    land: Dict[str, Any],
    *,
    reuse_thread_id: str = "",
) -> str:
    """ترد مأموریت را بگیر یا بساز؛ برای یک فایل فقط یک ترد."""
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

    existing_tid = _find_existing_mission_thread(
        ph, code, preferred_tid=reuse_thread_id
    )
    if existing_tid:
        try:
            set_active_thread(ph, existing_tid, audience=AUDIENCE_PARTNER)
        except Exception:
            pass
        return existing_tid

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
    insta = str(copies.get("instagram") or copies.get("insta") or "").strip()
    title_bit = f" — {title}" if title else ""
    assistant_msg = (
        f"خب، فایل {code}{title_bit} رو با هم جلو می‌بریم.\n"
        f"کارت فایل و متن آگهی همین پایین چته — "
        f"امروز دیوار بذار و یه استوری اینستا بزن."
    )
    agent_actions: list = []
    blocks = []
    if divar:
        blocks.append({"channel": "divar", "label": "متن دیوار", "text": divar})
    if insta:
        blocks.append({"channel": "instagram", "label": "کپشن اینستا", "text": insta})
    if blocks:
        agent_actions.append(
            {
                "type": "copy_blocks",
                "title": "متن آمادهٔ بازاریابی",
                "blocks": blocks,
                "land_code": code,
            }
        )
    append_exchange(
        ph,
        user_msg,
        assistant_msg,
        thread_id=tid,
        audience=AUDIENCE_PARTNER,
        assistant_land_codes=[code] if code else None,
        assistant_agent_actions=agent_actions or None,
        hide_user=True,
    )
    try:
        from app.ai.case_store import CASE_IN_PROGRESS, ensure_case_for_thread
        from app.ai.chat_events import emit_timeline

        ensure_case_for_thread(
            ph,
            tid,
            audience=AUDIENCE_PARTNER,
            land_code=code,
            case_type="mission",
            title=f"ماموریت {code}" if code else "ماموریت فروش",
        )
        emit_timeline(
            ph,
            event="mission_started",
            body=f"ماموریت جدید برای فایل {code} ایجاد شد." if code else "ماموریت جدید ایجاد شد.",
            audience=AUDIENCE_PARTNER,
            thread_id=tid,
            land_code=code,
            case_status=CASE_IN_PROGRESS,
        )
    except Exception:
        pass
    set_active_thread(ph, tid, audience=AUDIENCE_PARTNER)
    return tid


def _reactivate_mission_row(
    phone: str,
    land: Dict[str, Any],
    prev: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """مأموریت قبلی همین فایل را زنده کن و همان چت را نگه دار."""
    ph = _norm_phone(phone)
    code = str(land.get("code") or "").strip()
    prev_id = str(prev.get("id") or "").strip()
    if not ph or not code or not prev_id:
        return None
    thread_id = ""
    try:
        thread_id = _seed_mission_chat(
            ph, land, reuse_thread_id=str(prev.get("thread_id") or "")
        )
    except Exception:
        current_app.logger.exception(
            "mission chat reuse failed phone=%s code=%s", ph, code
        )
        thread_id = str(prev.get("thread_id") or "")

    rows = _missions_list()
    out: Optional[Dict[str, Any]] = None
    for row in rows:
        if str(row.get("id") or "").strip() != prev_id:
            # مأموریت‌های تکراری همین فایل را ببند تا لیست شلوغ نشود
            if (
                _norm_phone(str(row.get("partner_phone") or "")) == ph
                and str(row.get("land_code") or "").strip() == code
                and str(row.get("status") or "").strip().lower() == _STATUS_ACTIVE
            ):
                row["status"] = _STATUS_ABANDONED
                row["completed_at"] = _now_iso()
            continue
        row["status"] = _STATUS_ACTIVE
        row["thread_id"] = thread_id or str(row.get("thread_id") or "")
        row.pop("completed_at", None)
        row["last_followup_at"] = str(row.get("last_followup_at") or "")
        out = dict(row)
    if out:
        save_partner_missions(rows)
    return out


def _attach_mission_thread(
    phone: str,
    mission: Dict[str, Any],
) -> Dict[str, Any]:
    """اگر thread_id مأموریت مرده/خالی است، ترد موجود همان فایل را وصل کن."""
    ph = _norm_phone(phone)
    mid = str(mission.get("id") or "").strip()
    code = str(mission.get("land_code") or "").strip()
    if not ph or not mid or not code:
        return dict(mission)

    land = _land_by_code(code) or {"code": code, "title": ""}
    old_tid = str(mission.get("thread_id") or "").strip()
    try:
        new_tid = _seed_mission_chat(ph, land, reuse_thread_id=old_tid)
    except Exception:
        current_app.logger.exception(
            "attach mission thread failed phone=%s code=%s", ph, code
        )
        return dict(mission)

    if new_tid == old_tid:
        return dict(mission)

    rows = _missions_list()
    out = dict(mission)
    for row in rows:
        if str(row.get("id") or "").strip() != mid:
            continue
        row["thread_id"] = new_tid
        out = dict(row)
        break
    save_partner_missions(rows)
    out["thread_id"] = new_tid
    return out


def ensure_random_mission(phone: str) -> Optional[Dict[str, Any]]:
    """
    بازنشسته: مأموریت تصادفی حذف شد.
    جریان محصول = بازاریاب فروش از چت (مشتری→فایل یا نوع فایل→معرفی).
    claim_express_land_for_partner همچنان برای گرفتن فایل از چت فعال است.
    """
    return None


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
    agent_actions: list | None = None,
) -> bool:
    """پیام کوتاه مربی داخل ترد مأموریت (بدون پیام کاربر)."""
    text = (body or "").strip()
    tid = (thread_id or "").strip()
    actions = [a for a in (agent_actions or []) if isinstance(a, dict)][:3]
    if (not text and not actions) or not tid:
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
            assistant_agent_actions=actions or None,
        )
        mark_mission_followup(phone, land_code)
        return True
    except Exception:
        current_app.logger.exception(
            "mission chat followup failed phone=%s code=%s", phone, land_code
        )
        return False
