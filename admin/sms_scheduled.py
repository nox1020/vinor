# -*- coding: utf-8 -*-
"""زمان‌بندی ارسال پیامک مستقیم ادمین (آنی / یک‌بار / تکرارشونده) — وقت تهران."""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, current_app

from admin.sms_recipients import count_sms_recipients, load_sms_recipients, recipient_group_label
from app.services.sms import send_sms_direct
from app.services.sms_config import get_sms_line_number
from app.utils.dates import format_display_jalali_datetime, tehran_now, to_en_digits
from app.utils.storage import load_sms_history, save_sms_history

TEHRAN_FALLBACK = timezone(timedelta(hours=3, minutes=30))

RECURRENCE_DAILY = "daily"
RECURRENCE_WEEKLY = "weekly"
RECURRENCE_MONTHLY = "monthly"

SEND_TIMING_INSTANT = "instant"
SEND_TIMING_SCHEDULED = "scheduled"
SEND_TIMING_RECURRING = "recurring"

_STATUS_PENDING = "pending"
_STATUS_RUNNING = "running"
_STATUS_COMPLETED = "completed"
_STATUS_CANCELLED = "cancelled"

_WEEKDAY_LABELS = {
    5: "شنبه",
    6: "یکشنبه",
    0: "دوشنبه",
    1: "سه‌شنبه",
    2: "چهارشنبه",
    3: "پنجشنبه",
    4: "جمعه",
}

_scheduler_started = False
_run_lock = threading.Lock()


def _tehran_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Tehran")
    except Exception:
        return TEHRAN_FALLBACK


def _to_tehran(dt: datetime) -> datetime:
    """aware → تهران؛ naive را زمان دیوار تهران فرض می‌کند (نه UTC)."""
    tz = _tehran_tz()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def format_tehran_iso_display(iso_or_dt: Any) -> str:
    """نمایش شمسی + ساعت تهران (هم‌سبک هدر ادمین)."""
    if iso_or_dt is None:
        return "—"
    if isinstance(iso_or_dt, datetime):
        return format_display_jalali_datetime(_to_tehran(iso_or_dt).isoformat())
    s = str(iso_or_dt or "").strip()
    if not s:
        return "—"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return format_display_jalali_datetime(_to_tehran(dt).isoformat())
    except ValueError:
        return format_display_jalali_datetime(s) or s


def _jobs_path(app=None) -> str:
    app = app or current_app._get_current_object()
    data_dir = os.path.join(app.instance_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "sms_scheduled_jobs.json")


def load_scheduled_jobs(app=None) -> List[Dict[str, Any]]:
    import json

    path = _jobs_path(app)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_scheduled_jobs(jobs: List[Dict[str, Any]], app=None) -> None:
    import json

    path = _jobs_path(app)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def parse_tehran_datetime(value: str) -> Optional[datetime]:
    """مقدار datetime-local یا ISO — ارقام فارسی OK؛ بدون offset = وقت تهران."""
    raw = to_en_digits(value or "").strip()
    if not raw:
        return None
    if " " in raw and "T" not in raw:
        raw = raw.replace(" ", "T", 1)
    try:
        if len(raw) == 16 and "T" in raw:
            raw = raw + ":00"
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return _to_tehran(dt)
    except ValueError:
        return None


def parse_time_hm(value: str) -> Optional[Tuple[int, int]]:
    raw = to_en_digits(value or "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _combine_tehran_date_time(day: datetime, hour: int, minute: int) -> datetime:
    local = _to_tehran(day)
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _coerce_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(to_en_digits(str(value)).strip())
    except (TypeError, ValueError):
        return default


def compute_next_recurring_run(
    *,
    freq: str,
    hour: int,
    minute: int,
    weekday: Optional[int] = None,
    month_day: Optional[int] = None,
    after: Optional[datetime] = None,
) -> datetime:
    now = _to_tehran(after) if after is not None else tehran_now()
    candidate = _combine_tehran_date_time(now, hour, minute)

    if freq == RECURRENCE_DAILY:
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    if freq == RECURRENCE_WEEKLY:
        wd = _coerce_int(weekday, 5)
        days_ahead = (wd - now.weekday()) % 7
        target = _combine_tehran_date_time(now + timedelta(days=days_ahead), hour, minute)
        if target <= now:
            target = target + timedelta(days=7)
        return target

    if freq == RECURRENCE_MONTHLY:
        dom = _coerce_int(month_day, now.day) or now.day
        dom = max(1, min(31, dom))
        year, month = now.year, now.month
        for _ in range(24):
            try:
                target = datetime(year, month, dom, hour, minute, tzinfo=_tehran_tz())
            except ValueError:
                if month == 12:
                    year, month = year + 1, 1
                else:
                    month += 1
                continue
            if target > now:
                return target
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
        return now + timedelta(days=30)

    return candidate if candidate > now else candidate + timedelta(days=1)


def select_recipients_for_job(
    recipients: List[Dict[str, Any]],
    job: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """گیرندگان یک اجرا — با send_limit؛ تکرارشونده به‌صورت چرخشی از offset."""
    if not recipients:
        return []
    raw_limit = job.get("send_limit")
    try:
        limit = int(raw_limit) if raw_limit is not None and str(raw_limit).strip() != "" else 0
    except (TypeError, ValueError):
        limit = 0
    if limit < 1 or limit >= len(recipients):
        return recipients
    if job.get("send_timing") == SEND_TIMING_SCHEDULED:
        return recipients[:limit]
    offset = int(job.get("send_offset") or 0) % len(recipients)
    return [recipients[(offset + i) % len(recipients)] for i in range(limit)]


def parse_send_limit(value: Any, group_size: int) -> Tuple[Optional[int], Optional[str]]:
    """None = کل گروه؛ عدد مثبت = حداکثر در هر اجرا."""
    if value is None or str(value).strip() == "":
        return None, None
    try:
        n = int(to_en_digits(str(value)).strip())
    except (TypeError, ValueError):
        return None, "تعداد ارسال در هر مرحله باید عدد باشد."
    if n < 1:
        return None, "حداقل یک گیرنده در هر مرحله لازم است."
    if group_size < 1:
        return None, "گروه گیرنده خالی است."
    if n > group_size:
        return None, f"تعداد ارسال نمی‌تواند بیشتر از {group_size} نفر گروه باشد."
    return n, None


def send_batch_summary(job: Dict[str, Any]) -> str:
    limit = job.get("send_limit")
    total = int(job.get("recipient_count") or 0)
    if limit:
        if job.get("send_timing") == SEND_TIMING_RECURRING:
            return f"{limit} نفر در هر اجرا (چرخشی از {total} نفر)"
        return f"{limit} نفر از {total} نفر گروه"
    return f"کل گروه ({total} نفر)"


def recurrence_summary(job: Dict[str, Any]) -> str:
    freq = job.get("recurrence_freq") or RECURRENCE_DAILY
    t = job.get("recurrence_time") or "09:00"
    if freq == RECURRENCE_DAILY:
        return f"هر روز ساعت {t}"
    if freq == RECURRENCE_WEEKLY:
        wd = _coerce_int(job.get("recurrence_weekday"), 5)
        label = _WEEKDAY_LABELS.get(wd, str(wd))
        return f"هر {label} ساعت {t}"
    if freq == RECURRENCE_MONTHLY:
        dom = _coerce_int(job.get("recurrence_day"), 1) or 1
        return f"هر ماه روز {dom} ساعت {t}"
    return t


def send_direct_to_recipients(
    recipients: List[Dict[str, Any]],
    message: str,
    line_number: str,
    *,
    source: str = "admin_colleagues_direct",
) -> Tuple[int, int, List[Dict[str, Any]]]:
    line_number = get_sms_line_number()
    sent, failed, failed_details = 0, 0, []
    history_batch: List[Dict[str, Any]] = []
    HISTORY_FLUSH_EVERY = 50

    def _flush_history() -> None:
        nonlocal history_batch
        if not history_batch:
            return
        try:
            history = load_sms_history(current_app) or []
            base_id = len(history)
            for i, row in enumerate(history_batch):
                row["id"] = base_id + i + 1
            history.extend(history_batch)
            if len(history) > 10000:
                history = history[-10000:]
            save_sms_history(history, current_app)
        except Exception as hist_err:
            current_app.logger.error("Failed to save SMS history: %s", hist_err)
        history_batch = []

    for partner in recipients:
        phone_normalized = partner["phone"]
        try:
            result = send_sms_direct(
                mobile=phone_normalized,
                message=message,
                line_number=line_number,
                record_history=False,
            )
            history_batch.append({
                "mobile": phone_normalized,
                "recipient_name": partner.get("name"),
                "template_id": None,
                "message": message,
                "parameters": {},
                "success": result.get("ok", False),
                "status_code": result.get("status", 0),
                "response": result.get("body", {}),
                "source": source,
                "created_at": tehran_now().isoformat(),
                "error": None if result.get("ok") else str(result.get("body", {}).get("message", "Unknown error")),
            })
            if len(history_batch) >= HISTORY_FLUSH_EVERY:
                _flush_history()

            if result.get("ok"):
                sent += 1
            else:
                failed += 1
                failed_details.append({
                    "phone": phone_normalized,
                    "name": partner.get("name"),
                    "error": result.get("body", {}).get("message", "Unknown error"),
                })
        except Exception as e:
            failed += 1
            failed_details.append({
                "phone": partner.get("phone", "unknown"),
                "name": partner.get("name", "unknown"),
                "error": str(e),
            })
    _flush_history()
    return sent, failed, failed_details


def create_scheduled_job(
    *,
    recipient_group: str,
    message: str,
    line_number: str,
    send_timing: str,
    scheduled_at: Optional[str] = None,
    recurrence_freq: Optional[str] = None,
    recurrence_time: Optional[str] = None,
    recurrence_weekday: Optional[int] = None,
    recurrence_day: Optional[int] = None,
    send_limit: Optional[Any] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    message = (message or "").strip()
    line_number = get_sms_line_number()
    if not message:
        return None, "متن پیامک الزامی است."

    from admin.sms_recipients import LARGE_GROUP_REQUIRE_BATCH

    total = count_sms_recipients(recipient_group)
    if total < 1:
        label = recipient_group_label(recipient_group)
        return None, f"هیچ گیرنده‌ای در گروه «{label}» با شماره معتبر یافت نشد."

    parsed_limit, limit_error = parse_send_limit(send_limit, total)
    if limit_error:
        return None, limit_error
    if total >= LARGE_GROUP_REQUIRE_BATCH and not parsed_limit:
        return None, (
            f"گروه {total} نفره است؛ برای جلوگیری از کندی، "
            f"«تعداد ارسال در هر مرحله» را مشخص کنید (مثلاً ۵۰ تا ۵۰۰)."
        )

    now = _to_tehran(tehran_now())
    job: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "status": _STATUS_PENDING,
        "send_timing": send_timing,
        "recipient_group": recipient_group,
        "recipient_count": total,
        "send_limit": parsed_limit,
        "send_offset": 0,
        "message": message,
        "line_number": line_number,
        "created_at": now.isoformat(),
        "next_run_at": None,
        "last_run_at": None,
        "runs_completed": 0,
        "last_result": None,
    }

    if send_timing == SEND_TIMING_SCHEDULED:
        run_at = parse_tehran_datetime(scheduled_at or "")
        if not run_at:
            return None, "تاریخ و ساعت ارسال نامعتبر است (وقت تهران)."
        if run_at <= now + timedelta(seconds=5):
            return None, (
                f"زمان ارسال باید بعد از ساعت تهران باشد "
                f"(الان: {format_tehran_iso_display(now)})."
            )
        job["scheduled_at"] = run_at.isoformat()
        job["next_run_at"] = run_at.isoformat()
    elif send_timing == SEND_TIMING_RECURRING:
        freq = (recurrence_freq or RECURRENCE_DAILY).strip().lower()
        if freq not in (RECURRENCE_DAILY, RECURRENCE_WEEKLY, RECURRENCE_MONTHLY):
            return None, "نوع تکرار نامعتبر است."
        parsed_time = parse_time_hm(recurrence_time or "")
        if not parsed_time:
            return None, "ساعت تکرار نامعتبر است (وقت تهران)."
        hour, minute = parsed_time
        wd = _coerce_int(recurrence_weekday, 5)
        dom = recurrence_day
        if freq == RECURRENCE_MONTHLY:
            dom = max(1, min(31, _coerce_int(dom, 1) or 1))
        next_run = compute_next_recurring_run(
            freq=freq,
            hour=hour,
            minute=minute,
            weekday=wd,
            month_day=dom,
            after=now,
        )
        job["recurrence_freq"] = freq
        job["recurrence_time"] = f"{hour:02d}:{minute:02d}"
        job["recurrence_weekday"] = wd
        job["recurrence_day"] = dom
        job["next_run_at"] = next_run.isoformat()
    else:
        return None, "نوع زمان‌بندی نامعتبر است."

    jobs = load_scheduled_jobs()
    jobs.append(job)
    save_scheduled_jobs(jobs)
    return job, None


def cancel_scheduled_job(job_id: str) -> bool:
    if not (job_id or "").strip():
        return False
    jobs = load_scheduled_jobs()
    changed = False
    for job in jobs:
        if job.get("id") != job_id:
            continue
        if job.get("status") not in (_STATUS_PENDING, _STATUS_RUNNING):
            return False
        job["status"] = _STATUS_CANCELLED
        job["cancelled_at"] = tehran_now().isoformat()
        job.pop("run_started_at", None)
        changed = True
        break
    if changed:
        save_scheduled_jobs(jobs)
    return changed


def _recover_stale_running_jobs(jobs: List[Dict[str, Any]], now: datetime) -> bool:
    """اگر اجرا نیمه‌کاره بماند (crash)، بعد از ۲۰ دقیقه دوباره pending شود."""
    changed = False
    for job in jobs:
        if job.get("status") != _STATUS_RUNNING:
            continue
        started_raw = job.get("run_started_at")
        recover = False
        if not started_raw:
            recover = True
        else:
            try:
                started = _to_tehran(
                    datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
                )
                recover = (now - started).total_seconds() > 20 * 60
            except ValueError:
                recover = True
        if recover:
            job["status"] = _STATUS_PENDING
            job.pop("run_started_at", None)
            prev = job.get("last_result") if isinstance(job.get("last_result"), dict) else {}
            job["last_result"] = {**prev, "recovered_stale_run": True}
            changed = True
    return changed


def list_active_scheduled_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    jobs = load_scheduled_jobs()
    active = [j for j in jobs if j.get("status") == _STATUS_PENDING]
    active.sort(key=lambda x: x.get("next_run_at") or "")
    out: List[Dict[str, Any]] = []
    for job in active[:limit]:
        row = dict(job)
        row["next_run_display"] = format_tehran_iso_display(job.get("next_run_at"))
        row["last_run_display"] = format_tehran_iso_display(job.get("last_run_at"))
        row["recurrence_label"] = (
            recurrence_summary(job) if job.get("send_timing") == SEND_TIMING_RECURRING else ""
        )
        row["send_batch_label"] = send_batch_summary(job)
        out.append(row)
    return out


def _execute_job(app: Flask, job: Dict[str, Any]) -> None:
    group = job.get("recipient_group") or "approved"
    total = count_sms_recipients(group)
    job["recipient_count"] = total
    if total < 1:
        job["last_result"] = {"sent": 0, "failed": 0, "error": "no_recipients"}
        return

    raw_limit = job.get("send_limit")
    try:
        limit = int(raw_limit) if raw_limit is not None and str(raw_limit).strip() != "" else 0
    except (TypeError, ValueError):
        limit = 0

    offset = _coerce_int(job.get("send_offset"), 0) or 0
    if limit > 0 and limit < total:
        batch = load_sms_recipients(group, limit=limit, offset=offset, validate=False)
    else:
        batch = load_sms_recipients(group, validate=False)

    if not batch:
        job["last_result"] = {"sent": 0, "failed": 0, "error": "no_recipients"}
        return

    source = "admin_colleagues_scheduled"
    if job.get("send_timing") == SEND_TIMING_RECURRING:
        source = "admin_colleagues_recurring"

    sent, failed, _ = send_direct_to_recipients(
        batch,
        job.get("message") or "",
        get_sms_line_number(),
        source=source,
    )
    job["last_result"] = {"sent": sent, "failed": failed, "batch_size": len(batch)}
    job["last_run_at"] = tehran_now().isoformat()
    job["runs_completed"] = int(job.get("runs_completed") or 0) + 1

    if job.get("send_timing") == SEND_TIMING_RECURRING and limit > 0 and total > limit:
        job["send_offset"] = (offset + limit) % total
        job["recipient_count"] = total


def process_due_scheduled_jobs(app: Flask) -> int:
    if not _run_lock.acquire(blocking=False):
        return 0

    processed = 0
    try:
        with app.app_context():
            jobs = load_scheduled_jobs(app)
            now = tehran_now()
            changed = _recover_stale_running_jobs(jobs, now)

            for job in jobs:
                if job.get("status") != _STATUS_PENDING:
                    continue
                next_raw = job.get("next_run_at")
                if not next_raw:
                    continue
                try:
                    next_run = _to_tehran(
                        datetime.fromisoformat(str(next_raw).replace("Z", "+00:00"))
                    )
                except ValueError:
                    continue
                if next_run > now:
                    continue

                job["status"] = _STATUS_RUNNING
                job["run_started_at"] = now.isoformat()
                changed = True
                try:
                    _execute_job(app, job)
                except Exception as e:
                    app.logger.exception("Scheduled SMS job %s failed: %s", job.get("id"), e)
                    job["last_result"] = {"sent": 0, "failed": 0, "error": str(e)}

                job.pop("run_started_at", None)

                if job.get("send_timing") == SEND_TIMING_RECURRING:
                    parsed = parse_time_hm(job.get("recurrence_time") or "")
                    if parsed:
                        hour, minute = parsed
                        job["next_run_at"] = compute_next_recurring_run(
                            freq=job.get("recurrence_freq") or RECURRENCE_DAILY,
                            hour=hour,
                            minute=minute,
                            weekday=_coerce_int(job.get("recurrence_weekday"), 5),
                            month_day=_coerce_int(job.get("recurrence_day"), 1),
                            after=tehran_now(),
                        ).isoformat()
                    else:
                        app.logger.error(
                            "Scheduled SMS job %s has invalid recurrence_time: %r",
                            job.get("id"),
                            job.get("recurrence_time"),
                        )
                        job["next_run_at"] = (now + timedelta(hours=1)).isoformat()
                    job["status"] = _STATUS_PENDING
                else:
                    job["status"] = _STATUS_COMPLETED

                processed += 1
                changed = True

            if changed:
                save_scheduled_jobs(jobs, app)
    finally:
        _run_lock.release()

    return processed


def _scheduler_loop(app: Flask) -> None:
    time.sleep(8)
    while True:
        try:
            process_due_scheduled_jobs(app)
        except Exception:
            try:
                app.logger.exception("SMS scheduled jobs tick failed")
            except Exception:
                pass
        time.sleep(20)


def schedule_admin_sms_jobs(app: Flask) -> None:
    """PC: thread. هاست اشتراکی: lazy tick خودکار روی درخواست (بدون cron)."""
    global _scheduler_started
    if _scheduler_started:
        return
    if os.environ.get("VINOR_DISABLE_SMS_SCHEDULER", "").strip().lower() in ("1", "true", "yes"):
        app.logger.info("Admin SMS scheduler disabled via VINOR_DISABLE_SMS_SCHEDULER")
        return
    env_raw = os.environ.get("VINOR_ADMIN_SMS_SCHEDULER", "").strip().lower()
    if env_raw in ("0", "false", "no", "off"):
        from app.utils.lazy_scheduler import install_lazy_tick

        _scheduler_started = True

        def _should() -> bool:
            return True

        def _run() -> None:
            process_due_scheduled_jobs(app)

        install_lazy_tick(
            app,
            name="admin-sms",
            should_run=_should,
            run=_run,
            min_interval_sec=30,
        )
        return
    # env خالی / 1 / debug همگی روشن
    _scheduler_started = True
    threading.Thread(
        target=_scheduler_loop,
        args=(app,),
        daemon=True,
        name="vinor-admin-sms-scheduler",
    ).start()
    debug_on = bool(getattr(app, "debug", False)) or os.environ.get("FLASK_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    app.logger.info(
        "Admin SMS scheduled jobs runner started (interval=20s, tz=Asia/Tehran, debug=%s, env=%s)",
        debug_on,
        env_raw or "(default-on)",
    )
