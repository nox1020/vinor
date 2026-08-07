# -*- coding: utf-8 -*-
"""پیامک چرخهٔ عمر Vinor Plus — فعال‌سازی، تمدید، یادآوری و انقضا."""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from flask import current_app, Flask

from app.services.sms import (
    is_valid_iran_mobile,
    normalize_iran_mobile,
    send_sms_direct,
    sms_is_infrastructure_error,
)
from app.services.sms_config import get_sms_line_number
from app.utils.dates import format_display_jalali_date
from app.utils.storage import (
    _load,
    _save,
    ensure_file,
    load_settings,
    load_sms_history,
    save_sms_history,
)

from .plus_subscription import (
    PLUS_RENEW_WINDOW_DAYS,
    plus_subscription_view,
)

_DEFAULT_ACTIVATION = (
    "وینور\nVinor Plus برای شما فعال شد.\nاز امتیازهای پلاس در پنل همکاری استفاده کنید."
)
_DEFAULT_RENEWAL = (
    "وینور\nاشتراک پلاس با موفقیت تمدید شد.\nتا {expires_jalali} فعال است."
)
_DEFAULT_EXPIRY_REMINDER = (
    "وینور\nاشتراک پلاس رو به پایان است.\nلطفاً برای تمدید به پنل همکاری مراجعه کنید."
)
_DEFAULT_EXPIRED = (
    "وینور\nاشتراک پلاس منقضی شد.\nبرای ادامهٔ امتیازها، اشتراک را تمدید کنید."
)

SMS_TYPE_ACTIVATION = "plus_activated"
SMS_TYPE_RENEWAL = "plus_renewed"
SMS_TYPE_EXPIRY_REMINDER = "plus_expiry_reminder"
SMS_TYPE_EXPIRED = "plus_expired"


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def plus_partner_sms_feature_enabled() -> bool:
    """فلگ env — پیش‌فرض روشن."""
    return _env_bool("VINOR_PLUS_SMS_ENABLED", "1")


def _plus_sms_cfg() -> Dict[str, Any]:
    try:
        from .zarinpal_config import get_zarinpal_settings

        zp = get_zarinpal_settings()
    except Exception:
        zp = {}
    if not isinstance(zp, dict):
        zp = {}
    enabled = zp.get("partner_sms_enabled")
    if enabled is None:
        sms_on = True
    elif isinstance(enabled, bool):
        sms_on = enabled
    else:
        sms_on = str(enabled).strip().lower() in ("1", "true", "yes", "on")
    return {
        "enabled": sms_on,
        "activation": str(zp.get("sms_activation_message") or "").strip(),
        "renewal": str(zp.get("sms_renewal_message") or "").strip(),
        "expiry_reminder": str(zp.get("sms_expiry_reminder_message") or "").strip(),
        "expired": str(zp.get("sms_expired_message") or "").strip(),
    }


def plus_partner_sms_enabled() -> bool:
    if not plus_partner_sms_feature_enabled():
        return False
    try:
        from .zarinpal_config import plus_system_enabled

        if not plus_system_enabled():
            return False
    except Exception:
        pass
    return bool(_plus_sms_cfg().get("enabled"))


def _first_name(full_name: str, phone: str = "") -> str:
    name = (full_name or "").strip()
    if not name:
        name = (phone or "").strip()
    if not name:
        return "همکار"
    return name.split()[0]


def _apply_placeholders(
    template: str,
    *,
    name: str,
    phone: str,
    expires_jalali: str = "",
    days_remaining: str = "",
) -> str:
    first = _first_name(name, phone)
    return (
        template.replace("{name}", first)
        .replace("{partner_name}", first)
        .replace("{phone}", phone)
        .replace("{partner_phone}", phone)
        .replace("{expires_jalali}", expires_jalali)
        .replace("{days_remaining}", days_remaining)
    )


def build_plus_activation_sms_message(
    *,
    name: str = "",
    phone: str = "",
    expires_jalali: str = "",
    days_remaining: str = "",
    custom_template: str = "",
) -> str:
    tpl = (custom_template or "").strip() or _DEFAULT_ACTIVATION
    return _apply_placeholders(
        tpl,
        name=name,
        phone=phone,
        expires_jalali=expires_jalali,
        days_remaining=days_remaining,
    )


def build_plus_renewal_sms_message(
    *,
    name: str = "",
    phone: str = "",
    expires_jalali: str = "",
    days_remaining: str = "",
    custom_template: str = "",
) -> str:
    tpl = (custom_template or "").strip() or _DEFAULT_RENEWAL
    return _apply_placeholders(
        tpl,
        name=name,
        phone=phone,
        expires_jalali=expires_jalali,
        days_remaining=days_remaining,
    )


def build_plus_expiry_reminder_sms_message(
    *,
    name: str = "",
    phone: str = "",
    expires_jalali: str = "",
    days_remaining: str = "",
    custom_template: str = "",
) -> str:
    tpl = (custom_template or "").strip() or _DEFAULT_EXPIRY_REMINDER
    return _apply_placeholders(
        tpl,
        name=name,
        phone=phone,
        expires_jalali=expires_jalali,
        days_remaining=days_remaining,
    )


def build_plus_expired_sms_message(
    *,
    name: str = "",
    phone: str = "",
    expires_jalali: str = "",
    days_remaining: str = "",
    custom_template: str = "",
) -> str:
    tpl = (custom_template or "").strip() or _DEFAULT_EXPIRED
    return _apply_placeholders(
        tpl,
        name=name,
        phone=phone,
        expires_jalali=expires_jalali,
        days_remaining=days_remaining,
    )


def _state_path(app=None) -> str:
    return ensure_file("PLUS_SMS_STATE_FILE", "plus_sms_state.json", {}, app or current_app)


def _load_state() -> Dict[str, Any]:
    data = _load(_state_path())
    return data if isinstance(data, dict) else {}


def _save_state(state: Dict[str, Any]) -> None:
    _save(_state_path(), state)


def _dedup_key(sms_type: str, mobile: str, suffix: str = "") -> str:
    base = f"{sms_type}:{mobile}"
    if suffix:
        return f"{base}:{suffix}"
    return base


def _already_sent(state: Dict[str, Any], sms_type: str, mobile: str, suffix: str = "") -> bool:
    sent = state.get("sent") if isinstance(state.get("sent"), dict) else {}
    return bool(sent.get(_dedup_key(sms_type, mobile, suffix)))


def _mark_sent(state: Dict[str, Any], sms_type: str, mobile: str, suffix: str = "") -> None:
    sent = state.get("sent")
    if not isinstance(sent, dict):
        sent = {}
    sent[_dedup_key(sms_type, mobile, suffix)] = datetime.utcnow().isoformat() + "Z"
    state["sent"] = sent


def _append_sms_history(entry: dict) -> None:
    try:
        history = load_sms_history(current_app) or []
        if not isinstance(history, list):
            history = []
        history.append(entry)
        if len(history) > 5000:
            history = history[-5000:]
        save_sms_history(history, current_app)
    except Exception as exc:
        try:
            current_app.logger.exception("Plus SMS history append failed: %s", exc)
        except Exception:
            pass


def _sms_line() -> str:
    settings = load_settings(current_app) or {}
    return (settings.get("sms_line_number") or get_sms_line_number() or "09981801922").strip()


def _send_partner_message(
    *,
    mobile: str,
    message: str,
    sms_type: str,
    partner_phone: str,
    dedupe_suffix: str = "",
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not plus_partner_sms_enabled():
        return {"ok": False, "skipped": True, "error": "plus_sms_disabled"}

    if not message:
        return {"ok": False, "skipped": True, "error": "empty_message"}

    run_state = state if isinstance(state, dict) else _load_state()
    if dedupe_suffix and _already_sent(run_state, sms_type, mobile, dedupe_suffix):
        return {"ok": True, "skipped": True, "error": "already_sent"}

    line = _sms_line()
    sms_result = send_sms_direct(mobile=mobile, message=message, line_number=line, record_history=False)
    ok = bool(sms_result.get("ok"))
    err: Optional[str] = None
    body = sms_result.get("body") or {}
    if not ok:
        err = str(body.get("message") or body.get("error") or "sms_send_failed")
        if sms_is_infrastructure_error(err):
            sms_result = send_sms_direct(mobile=mobile, message=message, line_number=line, record_history=False)
            ok = bool(sms_result.get("ok"))
            body = sms_result.get("body") or {}
            if ok:
                err = None
            else:
                err = str(body.get("message") or body.get("error") or err)

    if not ok:
        try:
            current_app.logger.error(
                "Plus partner SMS failed type=%s mobile=%s status=%s body=%s",
                sms_type,
                mobile,
                sms_result.get("status"),
                body,
            )
        except Exception:
            pass

    if ok and dedupe_suffix:
        _mark_sent(run_state, sms_type, mobile, dedupe_suffix)
        _save_state(run_state)

    _append_sms_history({
        "type": sms_type,
        "mobile": mobile,
        "partner_phone": partner_phone,
        "message": message,
        "ok": ok,
        "success": ok,
        "error": err,
        "status_code": sms_result.get("status", 0),
        "response": body,
        "dedupe_suffix": dedupe_suffix,
        "source": "vinor_plus_lifecycle",
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    return {"ok": ok, "skipped": False, "error": err}


def _context_from_profile(profile: Optional[Dict[str, Any]], phone: str) -> Dict[str, str]:
    name = ""
    if isinstance(profile, dict):
        name = str(profile.get("name") or profile.get("full_name") or "").strip()
    mobile = normalize_iran_mobile(phone)
    view = plus_subscription_view(profile if isinstance(profile, dict) else None)
    expires_iso = str(view.get("expires_at") or "").strip()
    jalali = str(view.get("expires_at_jalali") or "").strip()
    if not jalali and expires_iso:
        jalali = format_display_jalali_date(expires_iso[:10])
    rem = view.get("days_remaining")
    days_str = str(int(rem)) if rem is not None else ""
    return {
        "name": name,
        "phone": mobile,
        "expires_jalali": jalali,
        "days_remaining": days_str,
        "expires_at": expires_iso,
        "status": str(view.get("status") or "none"),
    }


def notify_plus_payment_success_sms(
    *,
    partner_phone: str,
    partner_name: str = "",
    profile: Optional[Dict[str, Any]] = None,
    was_renewal: bool = False,
    transaction_id: str = "",
) -> Dict[str, Any]:
    """
    پس از verify موفق — یک پیامک per transaction_id (idempotent روی re-verify).
    """
    try:
        if not plus_partner_sms_enabled():
            return {"ok": False, "skipped": True, "error": "plus_sms_disabled"}

        mobile = normalize_iran_mobile(partner_phone)
        if not is_valid_iran_mobile(mobile):
            return {"ok": False, "skipped": True, "error": "invalid_partner_phone"}

        tid = str(transaction_id or "").strip()
        sms_type = SMS_TYPE_RENEWAL if was_renewal else SMS_TYPE_ACTIVATION
        dedupe = tid or f"payment:{mobile}:{sms_type}"

        cfg = _plus_sms_cfg()
        ctx = _context_from_profile(profile, mobile)
        if partner_name:
            ctx["name"] = partner_name

        if was_renewal:
            msg = build_plus_renewal_sms_message(
                name=ctx["name"],
                phone=ctx["phone"],
                expires_jalali=ctx["expires_jalali"],
                days_remaining=ctx["days_remaining"],
                custom_template=cfg.get("renewal") or "",
            )
        else:
            msg = build_plus_activation_sms_message(
                name=ctx["name"],
                phone=ctx["phone"],
                expires_jalali=ctx["expires_jalali"],
                days_remaining=ctx["days_remaining"],
                custom_template=cfg.get("activation") or "",
            )

        return _send_partner_message(
            mobile=mobile,
            message=msg,
            sms_type=sms_type,
            partner_phone=partner_phone,
            dedupe_suffix=dedupe,
        )
    except Exception as exc:
        try:
            current_app.logger.exception("notify_plus_payment_success_sms failed: %s", exc)
        except Exception:
            pass
        return {"ok": False, "skipped": False, "error": str(exc)}


def check_and_send_plus_lifecycle_reminder_sms(
    *,
    partner_phone: str,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """یادآوری پایان اشتراک یا اطلاع انقضا — با dedupe روی تاریخ پایان."""
    try:
        if not plus_partner_sms_enabled():
            return {"ok": False, "skipped": True, "error": "plus_sms_disabled"}

        mobile = normalize_iran_mobile(partner_phone)
        if not is_valid_iran_mobile(mobile):
            return {"ok": False, "skipped": True, "error": "invalid_partner_phone"}

        prof = profile if isinstance(profile, dict) else None
        ctx = _context_from_profile(prof, mobile)
        status = ctx["status"]
        expires_at = ctx["expires_at"]
        if not expires_at:
            return {"ok": False, "skipped": True, "error": "no_expiry"}

        cfg = _plus_sms_cfg()
        suffix = expires_at

        if status == "active":
            try:
                rem = int(ctx["days_remaining"] or "0")
            except (TypeError, ValueError):
                rem = 0
            if rem <= 0 or rem > PLUS_RENEW_WINDOW_DAYS:
                return {"ok": False, "skipped": True, "error": "not_in_renew_window"}
            msg = build_plus_expiry_reminder_sms_message(
                name=ctx["name"],
                phone=ctx["phone"],
                expires_jalali=ctx["expires_jalali"],
                days_remaining=ctx["days_remaining"],
                custom_template=cfg.get("expiry_reminder") or "",
            )
            return _send_partner_message(
                mobile=mobile,
                message=msg,
                sms_type=SMS_TYPE_EXPIRY_REMINDER,
                partner_phone=partner_phone,
                dedupe_suffix=suffix,
            )

        if status == "expired":
            msg = build_plus_expired_sms_message(
                name=ctx["name"],
                phone=ctx["phone"],
                expires_jalali=ctx["expires_jalali"],
                days_remaining=ctx["days_remaining"],
                custom_template=cfg.get("expired") or "",
            )
            return _send_partner_message(
                mobile=mobile,
                message=msg,
                sms_type=SMS_TYPE_EXPIRED,
                partner_phone=partner_phone,
                dedupe_suffix=suffix,
            )

        return {"ok": False, "skipped": True, "error": "no_lifecycle_event"}
    except Exception as exc:
        try:
            current_app.logger.exception("check_and_send_plus_lifecycle_reminder_sms failed: %s", exc)
        except Exception:
            pass
        return {"ok": False, "skipped": False, "error": str(exc)}


def defer_plus_lifecycle_sms_check(app: Flask, phone: str, profile: Optional[Dict[str, Any]] = None) -> None:
    """بررسی یادآوری/انقضا در پس‌زمینه — مسیر اصلی مسدود نشود."""
    ph = (phone or "").strip()
    if not ph:
        return
    prof = profile if isinstance(profile, dict) else None

    def _worker() -> None:
        with app.app_context():
            try:
                check_and_send_plus_lifecycle_reminder_sms(
                    partner_phone=ph,
                    profile=prof,
                )
            except Exception:
                app.logger.exception("deferred plus lifecycle SMS failed phone=%s", ph)

    threading.Thread(target=_worker, daemon=True).start()
