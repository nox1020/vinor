# -*- coding: utf-8 -*-
"""پیامک تبریک تولد و سالگرد عضویت در وینور — برای کاربران/همکاران."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, current_app

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

from ..services.sms import is_valid_iran_mobile, normalize_iran_mobile, send_sms_direct
from ..services.sms_config import get_sms_line_number
from ..utils.dates import gregorian_to_jalali, parse_datetime_safe
from ..utils.storage import (
    ensure_file,
    load_express_partners,
    load_settings,
    load_sms_history,
    load_users,
    save_sms_history,
    _load,
    _save,
)

_APPROVED_PARTNER_STATUSES = frozenset({"approved", "active", "enabled", "ok", "true", "1"})
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_JALALI_MONTHS = (
    "",
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
_YEAR_WORDS = {
    1: "یک",
    2: "دو",
    3: "سه",
    4: "چهار",
    5: "پنج",
    6: "شش",
    7: "هفت",
    8: "هشت",
    9: "نه",
    10: "ده",
}


def _tehran_now() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Tehran"))
        except Exception:
            pass
    return datetime.now()


def _jalali_today() -> Tuple[int, int, int]:
    now = _tehran_now()
    return gregorian_to_jalali(now.year, now.month, now.day)


def _jalali_today_key() -> str:
    jy, jm, jd = _jalali_today()
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def _fa_num(value: Any) -> str:
    return "".join(_PERSIAN_DIGITS[int(c)] for c in str(value))


def _first_name(full_name: str) -> str:
    name = (full_name or "").strip()
    if not name:
        return "دوست"
    parts = name.split()
    return parts[0] if parts else name


def _year_phrase(years: int) -> str:
    if years in _YEAR_WORDS:
        return f"{_YEAR_WORDS[years]} سال"
    return f"{_fa_num(years)} سال"


def _is_partner_approved(profile: Dict[str, Any]) -> bool:
    if not isinstance(profile, dict):
        return False
    status = str(profile.get("status") or "").strip().lower()
    return profile.get("status") is True or status in _APPROVED_PARTNER_STATUSES


def _parse_jalali_birth_md(birth_date: str) -> Optional[Tuple[int, int]]:
    """استخراج ماه/روز شمسی از birth_date (مثلاً 1370/5/15)."""
    raw = (birth_date or "").strip()
    if not raw or "/" not in raw:
        return None
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if len(parts) < 3:
        return None
    try:
        jm = int(parts[1])
        jd = int(parts[2])
    except (TypeError, ValueError):
        return None
    if not (1 <= jm <= 12 and 1 <= jd <= 31):
        return None
    return jm, jd


def _membership_jalali(registered_at: str) -> Optional[Tuple[int, int, int]]:
    dt = parse_datetime_safe(registered_at)
    if not dt or dt.year <= 1970:
        return None
    return gregorian_to_jalali(dt.year, dt.month, dt.day)


def _membership_years(jy_join: int, jm_join: int, jd_join: int) -> int:
    jy_now, jm_now, jd_now = _jalali_today()
    years = jy_now - jy_join
    if (jm_now, jd_now) < (jm_join, jd_join):
        years -= 1
    return max(0, years)


def _load_state() -> Dict[str, Any]:
    path = ensure_file("CELEBRATION_SMS_STATE_FILE", "celebration_sms_state.json", {}, current_app)
    data = _load(path)
    return data if isinstance(data, dict) else {}


def _save_state(state: Dict[str, Any]) -> None:
    path = ensure_file("CELEBRATION_SMS_STATE_FILE", "celebration_sms_state.json", {}, current_app)
    _save(path, state)


def _dedup_key(sms_type: str, mobile: str) -> str:
    return f"{sms_type}:{mobile}"


def _sent_today_from_state(state: Dict[str, Any], sms_type: str, mobile: str) -> bool:
    today = _jalali_today_key()
    sent = state.get("sent_today") if isinstance(state.get("sent_today"), dict) else {}
    return sent.get(_dedup_key(sms_type, mobile)) == today


def _mark_sent_today(state: Dict[str, Any], sms_type: str, mobile: str) -> None:
    today = _jalali_today_key()
    sent = state.get("sent_today")
    if not isinstance(sent, dict) or sent.get("_date") != today:
        sent = {"_date": today}
    sent[_dedup_key(sms_type, mobile)] = today
    state["sent_today"] = sent


def _append_sms_history_entries(entries: List[dict]) -> None:
    if not entries:
        return
    try:
        history = load_sms_history(current_app) or []
        if not isinstance(history, list):
            history = []
        history.extend(entries)
        if len(history) > 10000:
            history = history[-10000:]
        save_sms_history(history, current_app)
    except Exception:
        current_app.logger.exception("Failed to append celebration SMS history")


def _try_acquire_run_lock() -> Optional[int]:
    """قفل بین workerهای Passenger — فقط یک پروسه job روزانه را اجرا کند."""
    if os.name != "posix":
        return -1
    try:
        import fcntl

        from ..utils.storage import data_dir

        lock_path = os.path.join(data_dir(current_app), "celebration_sms.run.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except Exception:
        return None


def _release_run_lock(fd: Optional[int]) -> None:
    if fd is None or fd < 0:
        return
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except Exception:
        pass


def build_birthday_sms_message(*, name: str, jm: int, jd: int) -> str:
    first = _first_name(name)
    month_name = _JALALI_MONTHS[jm] if 1 <= jm <= 12 else ""
    day_fa = _fa_num(jd)
    date_hint = f"{day_fa} {month_name}" if month_name else f"{day_fa}ام"

    templates = [
        (
            f"وینور 🎂\n"
            f"{first} عزیز، تولدت مبارک!\n"
            f"امیدواریم {date_hint} و کل سال جدیدت پر از شادی، سلامتی و فروش‌های درخشان باشه."
        ),
        (
            f"وینور 🎉\n"
            f"{first} جان، تولدت فرخنده!\n"
            f"یک سال تازه پر از انرژی، موفقیت و معاملات بزرگ برات آرزومندیم."
        ),
        (
            f"وینور ✨\n"
            f"تولد {first} عزیز مبارک!\n"
            f"امروز روز توئه — امیدواریم همیشه برنده باشی و وینور کنارته."
        ),
    ]
    idx = abs(hash(name)) % len(templates)
    return templates[idx]


def build_membership_anniversary_sms_message(*, name: str, years: int) -> str:
    first = _first_name(name)
    yr = _year_phrase(years)

    if years == 1:
        body = (
            f"وینور 💚\n"
            f"{first} عزیز، یک سال از عضویتت در وینور گذشت!\n"
            f"ممنون که بخشی از خانواده ما هستی — سالی پر از رشد و درآمد بیشتر برات آرزومندیم."
        )
    elif years <= 3:
        body = (
            f"وینور 💚\n"
            f"{first} عزیز، {yr}ه که با وینور همراهی!\n"
            f"قدردان همراهی تو هستیم — امیدواریم سال جدیدت پر از موفقیت‌های بزرگ‌تر باشه."
        )
    else:
        body = (
            f"وینور 🌟\n"
            f"{first} عزیز، {yr} از عضویتت در وینور می‌گذره!\n"
            f"همکاری و اعتمادت برای ما ارزشمنده — سالی پر از رشد، سلامت و درآمد بیشتر برات آرزومندیم."
        )
    return body


def _collect_recipients() -> List[Dict[str, Any]]:
    partners = load_express_partners() or []
    users = load_users() or []
    users_by_phone: Dict[str, Dict[str, Any]] = {}
    for u in users if isinstance(users, list) else []:
        if not isinstance(u, dict):
            continue
        phone = normalize_iran_mobile(str(u.get("phone") or "").strip())
        if is_valid_iran_mobile(phone):
            users_by_phone[phone] = u

    out: Dict[str, Dict[str, Any]] = {}

    for p in partners if isinstance(partners, list) else []:
        if not isinstance(p, dict) or not _is_partner_approved(p):
            continue
        phone = normalize_iran_mobile(str(p.get("phone") or "").strip())
        if not is_valid_iran_mobile(phone):
            continue
        user = users_by_phone.get(phone) or {}
        registered_at = (
            str(p.get("created_at") or "").strip()
            or str(user.get("registered_at") or user.get("created_at") or "").strip()
        )
        out[phone] = {
            "phone": phone,
            "name": str(p.get("name") or p.get("full_name") or user.get("name") or phone).strip(),
            "birth_date": str(p.get("birth_date") or user.get("birth_date") or "").strip(),
            "registered_at": registered_at,
            "source": "express_partner",
        }

    for phone, user in users_by_phone.items():
        if phone in out:
            continue
        registered_at = str(user.get("registered_at") or user.get("created_at") or "").strip()
        if not registered_at:
            continue
        out[phone] = {
            "phone": phone,
            "name": str(user.get("name") or phone).strip(),
            "birth_date": str(user.get("birth_date") or "").strip(),
            "registered_at": registered_at,
            "source": "user",
        }

    return list(out.values())


def _send_celebration_sms(
    *,
    sms_type: str,
    mobile: str,
    name: str,
    message: str,
    line_number: str,
    state: Dict[str, Any],
    history_batch: List[dict],
    dry_run: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if _sent_today_from_state(state, sms_type, mobile):
        return {"ok": True, "skipped": True, "reason": "already_sent_today"}

    if dry_run:
        current_app.logger.info(
            "Celebration SMS dry-run type=%s mobile=%s message=%s",
            sms_type,
            mobile,
            message.replace("\n", " | "),
        )
        _mark_sent_today(state, sms_type, mobile)
        return {"ok": True, "skipped": False, "dry_run": True}

    result = send_sms_direct(mobile=mobile, message=message, line_number=line_number)
    ok = bool(result.get("ok"))
    err = None
    if not ok:
        body = result.get("body") or {}
        err = str(body.get("message") or body.get("error") or "sms_send_failed")

    entry = {
        "type": sms_type,
        "mobile": mobile,
        "recipient_name": name,
        "message": message,
        "ok": ok,
        "success": ok,
        "error": err,
        "status_code": result.get("status", 0),
        "response": result.get("body", {}),
        "jalali_date": _jalali_today_key(),
        "source": "daily_celebration",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    if extra:
        entry.update(extra)
    history_batch.append(entry)
    if ok:
        _mark_sent_today(state, sms_type, mobile)
    return {"ok": ok, "skipped": False, "error": err}


def run_daily_celebration_sms(*, dry_run: bool = False, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """بررسی امروز و ارسال پیامک تبریک تولد / سالگرد عضویت."""
    _, jm_now, jd_now = _jalali_today()
    settings = load_settings(current_app) or {}
    line_number = (
        settings.get("sms_line_number") or get_sms_line_number() or "300089930616"
    ).strip()

    run_state = state if isinstance(state, dict) else _load_state()
    history_batch: List[dict] = []
    recipients = _collect_recipients()
    stats = {
        "date": _jalali_today_key(),
        "recipients_total": len(recipients),
        "birthday_sent": 0,
        "birthday_skipped": 0,
        "birthday_failed": 0,
        "anniversary_sent": 0,
        "anniversary_skipped": 0,
        "anniversary_failed": 0,
        "dry_run": dry_run,
    }

    for person in recipients:
        phone = person["phone"]
        name = person.get("name") or phone

        birth_md = _parse_jalali_birth_md(person.get("birth_date") or "")
        if birth_md and birth_md == (jm_now, jd_now):
            msg = build_birthday_sms_message(name=name, jm=jm_now, jd=jd_now)
            res = _send_celebration_sms(
                sms_type="user_birthday",
                mobile=phone,
                name=name,
                message=msg,
                line_number=line_number,
                state=run_state,
                history_batch=history_batch,
                dry_run=dry_run,
                extra={"birth_date": person.get("birth_date")},
            )
            if res.get("skipped"):
                stats["birthday_skipped"] += 1
            elif res.get("ok"):
                stats["birthday_sent"] += 1
            else:
                stats["birthday_failed"] += 1

        joined = _membership_jalali(person.get("registered_at") or "")
        if joined:
            jy_j, jm_j, jd_j = joined
            years = _membership_years(jy_j, jm_j, jd_j)
            if years >= 1 and (jm_j, jd_j) == (jm_now, jd_now):
                msg = build_membership_anniversary_sms_message(name=name, years=years)
                res = _send_celebration_sms(
                    sms_type="user_membership_anniversary",
                    mobile=phone,
                    name=name,
                    message=msg,
                    line_number=line_number,
                    state=run_state,
                    history_batch=history_batch,
                    dry_run=dry_run,
                    extra={
                        "membership_years": years,
                        "registered_at": person.get("registered_at"),
                    },
                )
                if res.get("skipped"):
                    stats["anniversary_skipped"] += 1
                elif res.get("ok"):
                    stats["anniversary_sent"] += 1
                else:
                    stats["anniversary_failed"] += 1

    if not dry_run:
        _append_sms_history_entries(history_batch)
        _save_state(run_state)

    current_app.logger.info(
        "Daily celebration SMS date=%s birthday=%s/%s anniversary=%s/%s dry_run=%s",
        stats["date"],
        stats["birthday_sent"],
        stats["birthday_failed"],
        stats["anniversary_sent"],
        stats["anniversary_failed"],
        dry_run,
    )
    return stats


def maybe_run_daily_celebration_sms(*, force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """یک‌بار در روز (بعد از ساعت ۹ تهران) اجرا می‌شود."""
    today = _jalali_today_key()
    state = _load_state()
    if not force and state.get("last_run_date") == today:
        return {"skipped": True, "reason": "already_ran_today", "date": today}

    now = _tehran_now()
    if not force and now.hour < 9:
        return {"skipped": True, "reason": "before_9am_tehran", "date": today}

    lock_fd = _try_acquire_run_lock()
    if lock_fd is None:
        return {"skipped": True, "reason": "another_worker_running", "date": today}

    try:
        state = _load_state()
        if not force and state.get("last_run_date") == today:
            return {"skipped": True, "reason": "already_ran_today", "date": today}

        result = run_daily_celebration_sms(dry_run=dry_run, state=state)
        if not dry_run:
            state["last_run_date"] = today
            state["last_run_at"] = datetime.utcnow().isoformat() + "Z"
            state["last_result"] = result
            _save_state(state)
        return result
    finally:
        _release_run_lock(lock_fd)


def _scheduler_loop(app: Flask) -> None:
    # بعد از بالا آمدن کامل اپ — از فشار همزمان با اولین درخواست‌ها جلوگیری می‌کند
    time.sleep(300)
    while True:
        try:
            with app.app_context():
                maybe_run_daily_celebration_sms()
        except Exception:
            app.logger.exception("Celebration SMS scheduler tick failed")
        time.sleep(3600)


def schedule_daily_celebration_sms(app: Flask) -> None:
    """زمان‌بندی ساعتی — فقط با VINOR_CELEBRATION_SMS_SCHEDULER=1 فعال شود."""
    if os.environ.get("VINOR_DISABLE_CELEBRATION_SMS", "").strip().lower() in ("1", "true", "yes"):
        app.logger.info("Celebration SMS scheduler disabled via VINOR_DISABLE_CELEBRATION_SMS")
        return
    if os.environ.get("VINOR_CELEBRATION_SMS_SCHEDULER", "").strip().lower() not in ("1", "true", "yes"):
        app.logger.info(
            "Celebration SMS in-process scheduler off (use cron script or set VINOR_CELEBRATION_SMS_SCHEDULER=1)"
        )
        return
    threading.Thread(
        target=_scheduler_loop,
        args=(app,),
        daemon=True,
        name="vinor-celebration-sms",
    ).start()
    app.logger.info("Celebration SMS daily scheduler started")
