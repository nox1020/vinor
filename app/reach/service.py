"""ارسال پیگیری از سیگنال ناظر — خریدار/فروشنده؛ همکار از sales_coach."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any

from flask import current_app

from app.reach.config import REACH_HOURS, reach_enabled, reach_notif_enabled, reach_sms_enabled

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

_LOCK = threading.Lock()
_STATE_NAME = "reach_nudge_state.json"
_LOCK_NAME = "reach_nudge.run.lock"


def _tehran_now() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Tehran"))
        except Exception:
            pass
    return datetime.now()


def _state_path() -> str:
    try:
        from app.utils.storage import data_dir

        return os.path.join(data_dir(), _STATE_NAME)
    except Exception:
        return os.path.join(os.getcwd(), "instance", "data", _STATE_NAME)


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not os.path.isfile(path):
        return {"users": {}, "slots": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"users": {}, "slots": {}}
    except Exception:
        return {"users": {}, "slots": {}}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _acquire_lock() -> bool:
    path = os.path.join(os.path.dirname(_state_path()), _LOCK_NAME)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time_age(path)
            if age > 1800:
                os.remove(path)
                return _acquire_lock()
        except Exception:
            pass
        return False
    except Exception:
        return False


def time_age(path: str) -> float:
    try:
        return max(0.0, datetime.now().timestamp() - os.path.getmtime(path))
    except Exception:
        return 0.0


def _release_lock() -> None:
    path = os.path.join(os.path.dirname(_state_path()), _LOCK_NAME)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _is_partner_phone(phone: str) -> bool:
    try:
        from app.express_partner.routes import _find_partner_record, _is_partner_approved
        from app.utils.storage import load_express_partners

        prof = _find_partner_record(load_express_partners() or [], phone)
        return bool(_is_partner_approved(prof))
    except Exception:
        return False


def _message_for_signal(snap: Any) -> tuple[str, str, str]:
    """(title, notif_body, sms_body) — هدف واضح + دعوت ورود به اپ وینور."""
    stage = str(getattr(snap, "stage", "") or "")
    land = str(getattr(snap, "land_code", "") or "").strip()
    land_bit = f" {land}" if land else ""
    cta = "وارد اپلیکیشن وینور شو و از چت ادامه بده."

    if stage == "deal":
        title = "معامله رو نهایی کن"
        body = (
            f"معامله فایل{land_bit} هنوز بازه — الان بهترین زمان برای بستنشه. "
            f"{cta}"
        )
        sms = (
            f"وینور\nمعامله{land_bit} هنوز بازه\n"
            f"وارد اپ وینور شو و از چت نهایی‌اش کن"
        )
    elif stage == "visit":
        title = "بازدیدت منتظر اقدامه"
        body = (
            f"بازدید فایل{land_bit} هنوز کامل نشده. "
            f"یک قدم کوچیک کافیه تا پرونده جلو بره. {cta}"
        )
        sms = (
            f"وینور\nبازدید{land_bit} منتظرته\n"
            f"وارد اپ وینور شو و از چت جلو ببر"
        )
    elif stage == "land":
        title = "این فایل هنوز منتظرته"
        body = (
            f"فایل{land_bit} رو دیدی ولی تصمیم نگرفتی. "
            f"اگر مناسبه، بازدید رو هماهنگ کن. {cta}"
        )
        sms = (
            f"وینور\nفایل{land_bit} منتظر تصمیمت هست\n"
            f"وارد اپ وینور شو و از چت بگو بریم جلو"
        )
    else:
        title = "هنوز بهترین فایل رو ندیدی"
        body = (
            "معیارت نصفه مونده؛ وینور منتظره تا بهترین گزینهٔ گرمابسرد رو برات جور کنه. "
            f"{cta}"
        )
        sms = (
            "وینور\nهنوز فایل مناسبت نهایی نشده\n"
            "وارد اپ وینور شو و از چت معیارت رو بگو"
        )
    return title, body, sms


def _clip_sms(text: str, *, limit: int = 160) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)] + "…"


def _send_one(
    phone: str,
    title: str,
    body: str,
    *,
    sms_body: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "phone": phone,
        "title": title,
        "body": body,
        "sms_body": sms_body or body,
        "notif": False,
        "sms": False,
    }
    if dry_run:
        item["dry_run"] = True
        return item
    if reach_notif_enabled():
        try:
            from app.services.notifications import add_notification

            add_notification(phone, title, body, ntype="reach", action_url="/ai")
            item["notif"] = True
        except Exception:
            pass
    if reach_sms_enabled():
        try:
            from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile, send_sms_direct

            ph = normalize_iran_mobile(phone) or phone
            if is_valid_iran_mobile(ph):
                send_sms_direct(ph, _clip_sms(sms_body or body))
                item["sms"] = True
        except Exception:
            pass
    return item


def run_buyer_reach_slot(
    *,
    slot_hour: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """پیگیری خریدار/فروشنده از سیگنال ناظر — بدون تأیید ادمین."""
    if not reach_enabled():
        return {"ok": False, "skipped": "disabled"}

    from app.supervisor.funnel import clear_reach_signal, list_reach_signals

    signals = list_reach_signals(limit=300)
    state = _load_state()
    users = state.setdefault("users", {})
    if not isinstance(users, dict):
        users = {}
        state["users"] = users

    day = _tehran_now().strftime("%Y-%m-%d")
    slot_key = f"{day}:{int(slot_hour)}"
    slots = state.setdefault("slots", {})
    if isinstance(slots, dict) and slots.get(slot_key) and not dry_run:
        return {"ok": True, "skipped": "slot_done", "slot": slot_hour}

    sent = 0
    skipped = 0
    results: list[dict[str, Any]] = []

    for snap in signals:
        phone = str(snap.user_key or "").strip()
        if not phone or phone.startswith("guest_") or phone.startswith("admin_"):
            skipped += 1
            continue
        # همکار تأییدشده را sales_coach پوشش می‌دهد
        if _is_partner_phone(phone):
            skipped += 1
            continue
        aud = (snap.audience or "").strip().lower()
        if aud in ("partner", "admin"):
            skipped += 1
            continue

        track = users.get(phone) if isinstance(users.get(phone), dict) else {}
        last_slot = str(track.get("last_slot") or "")
        if last_slot == slot_key:
            skipped += 1
            continue
        count = int(track.get("nudge_count") or 0)
        if count >= 12:
            skipped += 1
            continue

        title, body, sms_body = _message_for_signal(snap)
        item = _send_one(phone, title, body, sms_body=sms_body, dry_run=dry_run)
        item.update(
            {
                "stage": snap.stage,
                "land": snap.land_code,
                "audience": snap.audience,
                "slot": slot_hour,
            }
        )
        results.append(item)
        if item.get("notif") or item.get("sms") or dry_run:
            sent += 1
            if not dry_run:
                users[phone] = {
                    "last_slot": slot_key,
                    "nudge_count": count + 1,
                    "stage": snap.stage,
                    "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                try:
                    clear_reach_signal(phone)
                except Exception:
                    pass
        else:
            skipped += 1

    if not dry_run:
        slots[slot_key] = {"sent": sent, "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        # نگه داشتن فقط ۳۰ اسلات اخیر
        if isinstance(slots, dict) and len(slots) > 40:
            for k in sorted(slots.keys())[:-30]:
                slots.pop(k, None)
        state["slots"] = slots
        state["users"] = users
        _save_state(state)

    if sent > 0:
        try:
            from app.supervisor_agent.service import emit_domain_event

            emit_domain_event("reach_nudge_sent", sent_count=sent)
        except Exception:
            pass

    return {
        "ok": True,
        "slot": slot_hour,
        "sent": sent,
        "skipped": skipped,
        "results": results,
    }


def _active_slot_hour(now: datetime | None = None) -> int | None:
    now = now or _tehran_now()
    h = int(now.hour)
    if h in REACH_HOURS:
        return h
    return None


def maybe_run_reach_followup(
    *,
    force: bool = False,
    dry_run: bool = False,
    slot_hour: int | None = None,
) -> dict[str, Any]:
    """پیگیری خریدار از سیگنال ناظر — نوبت‌های ۱۰/۱۴/۲۰ تهران (برای cron)."""
    if not reach_enabled():
        return {"skipped": True, "reason": "disabled"}

    now = _tehran_now()
    hour = int(slot_hour) if slot_hour is not None else _active_slot_hour(now)
    if hour is None and not force:
        return {
            "skipped": True,
            "reason": "not_reach_slot",
            "hour": now.hour,
            "slots": list(REACH_HOURS),
        }
    if hour is None and force:
        hour = int(now.hour) if now.hour in REACH_HOURS else REACH_HOURS[0]

    from app.supervisor.funnel import refresh_funnels_for_reach

    refresh_funnels_for_reach()
    return run_buyer_reach_slot(slot_hour=int(hour), dry_run=dry_run)


def run_reach_slot(*, slot_hour: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """یک نوبت کامل: خریدار از ناظر + همکار از sales_coach."""
    if not reach_enabled():
        return {"ok": False, "reason": "disabled"}
    now = _tehran_now()
    hour = int(slot_hour if slot_hour is not None else now.hour)
    if hour not in REACH_HOURS and slot_hour is None:
        return {"ok": True, "skipped": "off_hours", "hour": hour}

    if not _acquire_lock() and not dry_run:
        return {"ok": False, "reason": "locked"}
    try:
        buyer = run_buyer_reach_slot(slot_hour=hour, dry_run=dry_run)
        partner: dict[str, Any] = {}
        try:
            from app.express_partner.sales_coach import run_sales_coach_nudge_slot

            partner = run_sales_coach_nudge_slot(slot_hour=hour, dry_run=dry_run)
        except Exception as exc:
            partner = {"ok": False, "error": str(exc)}
        return {"ok": True, "slot": hour, "buyer": buyer, "partner": partner}
    finally:
        if not dry_run:
            _release_lock()
