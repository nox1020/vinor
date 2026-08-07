"""ارسال پیگیری از سیگنال ناظر — خریدار/فروشنده؛ همکار از sales_coach."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any

from app.reach.config import reach_enabled, reach_hours, reach_notif_enabled, reach_sms_enabled
from app.utils.dates import tehran_now as _tehran_now

_LOCK = threading.Lock()
_STATE_NAME = "reach_nudge_state.json"
_LOCK_NAME = "reach_nudge.run.lock"


def _state_path() -> str:
    try:
        from app.utils.storage import data_dir

        return os.path.join(data_dir(), _STATE_NAME)
    except Exception:
        from app.utils.storage import _standalone_instance_path

        return os.path.join(_standalone_instance_path(), "data", _STATE_NAME)


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
    """(title, notif_body, sms_body) — لحن خودمونی کوتاه، شبیه پیامک بلوباک."""
    stage = str(getattr(snap, "stage", "") or "")
    land = str(getattr(snap, "land_code", "") or "").strip()
    land_bit = f" {land}" if land else ""

    if stage == "deal":
        title = "یه قدم مونده تموم شه"
        body = (
            f"معامله{land_bit} هنوز بازه. "
            f"بیا تو اپ وینور، از چت جمعش کن."
        )
        sms = (
            f"وینور\n"
            f"معامله‌ت{land_bit} هنوز بازه\n"
            f"بیا تو اپ، از چت تمومش کن"
        )
    elif stage == "visit":
        title = "بازدیدت مونده"
        body = (
            f"بازدید{land_bit} هنوز تموم نشده. "
            f"بیا تو اپ وینور، از چت بگو چیکار کنیم."
        )
        sms = (
            f"وینور\n"
            f"بازدیدت{land_bit} هنوز تموم نشده\n"
            f"بیا تو اپ، از چت جلو ببر"
        )
    elif stage == "land":
        title = "این فایل رو دیدی؟"
        body = (
            f"فایل{land_bit} رو دیدی ولی هنوز تصمیمی نگرفتی. "
            f"اگه خوبه، بیا تو اپ وینور بگو بریم بازدید."
        )
        sms = (
            f"وینور\n"
            f"فایل{land_bit} رو دیدی؟\n"
            f"بیا تو اپ بگو بریم جلو یا نه"
        )
    else:
        title = "کمکت کنیم پیدا کنی"
        body = (
            "معیارت هنوز نصفه است. "
            "بیا تو اپ وینور، از چت بگو چی می‌خوای تا برات جور کنیم."
        )
        sms = (
            "وینور\n"
            "هنوز فایل مناسبت پیدا نشده\n"
            "بیا تو اپ، از چت بگو چی می‌خوای"
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
        except Exception as exc:
            item["notif_error"] = str(exc)[:200]
            try:
                from flask import current_app

                current_app.logger.warning("Reach notif failed phone=%s: %s", phone, exc)
            except Exception:
                pass
    if reach_sms_enabled():
        try:
            from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile, send_sms_direct

            ph = normalize_iran_mobile(phone) or phone
            if is_valid_iran_mobile(ph):
                send_sms_direct(ph, _clip_sms(sms_body or body), history_source='reach')
                item["sms"] = True
            else:
                item["sms_error"] = "invalid_mobile"
        except Exception as exc:
            item["sms_error"] = str(exc)[:200]
            try:
                from flask import current_app

                current_app.logger.warning("Reach SMS failed phone=%s: %s", phone, exc)
            except Exception:
                pass
    return item


def _normalize_reach_phone(raw: str) -> str:
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

    ph = normalize_iran_mobile(raw) or ""
    return ph if is_valid_iran_mobile(ph) else ""


def _slot_already_done(slot_hour: int, *, now: datetime | None = None) -> bool:
    now = now or _tehran_now()
    slot_key = f"{now.strftime('%Y-%m-%d')}:{int(slot_hour)}"
    slots = _load_state().get("slots")
    return isinstance(slots, dict) and bool(slots.get(slot_key))


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
        phone = _normalize_reach_phone(str(snap.user_key or "").strip())
        if not phone:
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
    """نوبت جاری یا آخرین نوبت معوق امروز (تا قبل از نوبت بعدی).

    روی هاست بدون cron، هر ترافیک وب بعد از نوبت، همان نوبت را جمع می‌کند.
    """
    now = now or _tehran_now()
    h = int(now.hour)
    due: int | None = None
    for slot in reach_hours():
        if h >= int(slot):
            due = int(slot)
        else:
            break
    return due


def maybe_run_reach_followup(
    *,
    force: bool = False,
    dry_run: bool = False,
    slot_hour: int | None = None,
) -> dict[str, Any]:
    """پیگیری خریدار از سیگنال ناظر — نوبت‌های قابل‌تنظیم تهران (خودکار روی وب/PC)."""
    if not reach_enabled():
        return {"skipped": True, "reason": "disabled"}

    hours = reach_hours()
    now = _tehran_now()
    hour = int(slot_hour) if slot_hour is not None else _active_slot_hour(now)
    if hour is None and not force:
        return {
            "skipped": True,
            "reason": "not_reach_slot",
            "hour": now.hour,
            "slots": list(hours),
            "tehran": now.isoformat(),
        }
    if hour is None and force:
        hour = int(now.hour) if now.hour in hours else (hours[0] if hours else 10)

    # قبل از refresh سنگین — اگر نوبت انجام شده، زود خارج شو (مهم برای lazy tick هاست)
    if not dry_run and not force and _slot_already_done(hour, now=now):
        return {"ok": True, "skipped": "slot_done", "slot": hour}

    locked = False
    if not dry_run:
        if not _acquire_lock():
            return {"skipped": True, "reason": "locked", "slot": hour}
        locked = True
    try:
        from app.supervisor.funnel import refresh_funnels_for_reach

        refreshed = refresh_funnels_for_reach()
        result = run_buyer_reach_slot(slot_hour=int(hour), dry_run=dry_run)
        if isinstance(result, dict):
            result["refreshed"] = refreshed
            result["tehran"] = now.isoformat()
        return result
    finally:
        if locked:
            _release_lock()


def run_reach_slot(*, slot_hour: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """یک نوبت کامل: خریدار از ناظر + همکار از sales_coach."""
    if not reach_enabled():
        return {"ok": False, "reason": "disabled"}
    now = _tehran_now()
    hour = int(slot_hour) if slot_hour is not None else _active_slot_hour(now)
    if hour is None:
        return {"ok": True, "skipped": "off_hours", "hour": int(now.hour)}

    if not _acquire_lock() and not dry_run:
        return {"ok": False, "reason": "locked"}
    try:
        from app.supervisor.funnel import refresh_funnels_for_reach

        refresh_funnels_for_reach()
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
