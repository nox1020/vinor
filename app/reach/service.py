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


def _message_for_signal(snap: Any) -> tuple[str, str]:
    stage = str(getattr(snap, "stage", "") or "")
    land = str(getattr(snap, "land_code", "") or "").strip()
    code_bit = f" ({land})" if land else ""
    if stage == "deal":
        title = "پیگیری معامله"
        body = f"وینور: معامله{code_bit} هنوز باز است. از چت پیگیری کن تا نهایی شود."
    elif stage == "visit":
        title = "یادآوری بازدید"
        body = f"وینور: بازدید{code_bit} منتظر اقدام توست. از چت جلو ببر."
    elif stage == "land":
        title = "ادامهٔ پیشنهاد فایل"
        body = f"وینور: فایل{code_bit} را دیدی — برای بازدید یا تصمیم از چت ادامه بده."
    else:
        title = "ادامهٔ جستجو"
        body = "وینور: هنوز فایل مناسبت را نهایی نکردی. از چت معیارت را بگو تا بهترین گزینه را پیشنهاد دهیم."
    return title, body


def _send_one(phone: str, title: str, body: str, *, dry_run: bool) -> dict[str, Any]:
    item: dict[str, Any] = {"phone": phone, "title": title, "notif": False, "sms": False}
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
                sms = body if len(body) <= 160 else (body[:157] + "…")
                send_sms_direct(ph, sms)
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
        if not phone or phone.startswith("guest_"):
            skipped += 1
            continue
        # همکار تأییدشده را sales_coach پوشش می‌دهد
        if _is_partner_phone(phone):
            skipped += 1
            continue
        if (snap.audience or "").strip().lower() == "partner":
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

        title, body = _message_for_signal(snap)
        item = _send_one(phone, title, body, dry_run=dry_run)
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

    return {
        "ok": True,
        "slot": slot_hour,
        "sent": sent,
        "skipped": skipped,
        "results": results,
    }


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
