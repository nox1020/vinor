# -*- coding: utf-8 -*-
"""تأیید callback و شروع پرداخت Vinor Plus."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import flash, redirect, session, url_for

from .partner_session_sync import canonical_partner_phone, phones_match, sync_partner_session_after_plus
from .plus_grant import grant_vinor_plus_for_phone
from .plus_transactions import (
    STATUS_PAID,
    STATUS_PENDING,
    attach_authority,
    find_by_authority,
    mark_cancelled,
    mark_failed,
    mark_paid,
)
from .zarinpal_client import payment_request, payment_verify, start_pay_url
import logging

from .zarinpal_config import (
    effective_merchant_id,
    get_zarinpal_settings,
    payment_flow_active,
    plus_amount_toman,
)

_log = logging.getLogger(__name__)


def resolve_callback_url() -> str:
    cfg = get_zarinpal_settings()
    explicit = str(cfg.get("callback_url") or "").strip()
    if explicit:
        return explicit
    return url_for("express_partner.plus_zarinpal_callback", _external=True)


def begin_plus_payment(
    *,
    phone: str,
    partner_name: str,
) -> Tuple[bool, Optional[str], str]:
    """
    تراکنش pending + درخواست authority.
    برمی‌گرداند: (ok, redirect_url, error_message)
    """
    if not payment_flow_active():
        return False, None, "payment_not_configured"

    from .plus_transactions import create_pending

    cfg = get_zarinpal_settings()
    amount = plus_amount_toman()
    ph = canonical_partner_phone(phone)
    txn = create_pending(
        phone=ph,
        partner_name=partner_name,
        amount_toman=amount,
        description=str(cfg.get("description") or "Vinor Plus"),
    )
    cb = resolve_callback_url()
    req = payment_request(
        amount_toman=amount,
        callback_url=cb,
        description=str(txn.get("description") or ""),
        metadata={"mobile": phone, "order_id": txn.get("id")},
        merchant_id=effective_merchant_id(cfg),
        sandbox=bool(cfg.get("sandbox")),
    )
    if not req.get("ok"):
        err = str(req.get("error") or req.get("message") or "request_failed")
        _log.warning(
            "ZarinPal payment_request failed | phone=%s code=%s err=%s",
            ph,
            req.get("code"),
            err,
        )
        mark_failed(txn, message=err)
        return False, None, err

    authority = str(req.get("authority") or "").strip()
    attach_authority(txn, authority)
    pay_url = start_pay_url(authority, sandbox=bool(cfg.get("sandbox")))
    return True, pay_url, ""


def complete_plus_payment_from_callback(
    *,
    authority: str,
    status_param: str,
) -> Dict[str, Any]:
    """
    Idempotent: اگر قبلاً paid بود بدون grant دوباره، success برمی‌گردد.
    """
    auth = str(authority or "").strip()
    st = str(status_param or "").strip().upper()
    if not auth:
        return {"ok": False, "reason": "missing_authority"}
    txn = find_by_authority(auth)
    if not txn:
        return {"ok": False, "reason": "unknown_authority"}

    if str(txn.get("status") or "") == STATUS_PAID:
        return {"ok": True, "reason": "already_paid", "txn": txn, "granted": False}

    if st != "OK":
        mark_cancelled(txn, message=f"gateway_status={st or 'NOK'}")
        return {"ok": False, "reason": "user_cancelled", "txn": txn}

    amount = int(txn.get("amount_toman") or 0)
    cfg = get_zarinpal_settings()
    verify = payment_verify(
        authority=auth,
        amount_toman=amount,
        merchant_id=effective_merchant_id(cfg),
        sandbox=bool(cfg.get("sandbox")),
    )
    if not verify.get("ok"):
        mark_failed(
            txn,
            message=str(verify.get("error") or verify.get("message") or "verify_failed"),
            verify_code=verify.get("code"),
        )
        return {"ok": False, "reason": "verify_failed", "txn": txn, "verify": verify}

    txn = mark_paid(
        txn,
        ref_id=verify.get("ref_id"),
        verify_code=verify.get("code"),
        verify_message=str(verify.get("message") or ""),
        authority=auth,
    )
    grant = grant_vinor_plus_for_phone(
        str(txn.get("phone") or ""),
        partner_name=str(txn.get("partner_name") or ""),
    )
    if grant.get("ok"):
        try:
            from .plus_sms import notify_plus_payment_success_sms
            from .partner_session_sync import find_partner_record
            from app.utils.storage import load_express_partners

            ph = canonical_partner_phone(str(txn.get("phone") or ""))
            partners = load_express_partners() or []
            profile = find_partner_record(partners if isinstance(partners, list) else [], ph)
            notify_plus_payment_success_sms(
                partner_phone=ph,
                partner_name=str(txn.get("partner_name") or ""),
                profile=profile if isinstance(profile, dict) else None,
                was_renewal=bool(grant.get("already_special")),
                transaction_id=str(txn.get("id") or ""),
            )
        except Exception:
            _log.exception("Plus payment success SMS failed authority=%s", auth)
    return {
        "ok": True,
        "reason": "paid",
        "txn": txn,
        "grant": grant,
        "granted": bool(grant.get("ok")),
    }


def handle_callback_http(authority: str, status_param: str):
    """Redirect + flash برای route callback."""
    me = canonical_partner_phone(session.get("user_phone") or "")
    result = complete_plus_payment_from_callback(authority=authority, status_param=status_param)
    if result.get("ok"):
        txn = result.get("txn") if isinstance(result.get("txn"), dict) else {}
        txn_phone = canonical_partner_phone(str(txn.get("phone") or ""))
        if me and txn_phone and not phones_match(me, txn_phone):
            flash(
                "این پرداخت برای شمارهٔ دیگری ثبت شده است. با همان شماره‌ای که پرداخت کردید وارد شوید.",
                "error",
            )
            return redirect(url_for("express_partner.plus"))
        sync_partner_session_after_plus(me or txn_phone)
        if result.get("reason") == "already_paid":
            flash("پرداخت شما قبلاً تأیید شده است. اشتراک پلاس فعال است.", "success")
        else:
            grant = result.get("grant") if isinstance(result.get("grant"), dict) else {}
            if grant.get("already_special"):
                flash("پرداخت موفق بود. اشتراک Vinor Plus تمدید شد.", "success")
            else:
                flash("پرداخت موفق بود. Vinor Plus برای حساب شما فعال شد.", "success")
        return redirect(url_for("express_partner.plus", plus_activated="1"))
    reason = result.get("reason") or "failed"
    if reason == "user_cancelled":
        flash("پرداخت لغو شد.", "warning")
    elif reason == "verify_failed":
        flash("تأیید پرداخت ناموفق بود. در صورت کسر وجه با پشتیبانی تماس بگیرید.", "error")
    else:
        flash("پرداخت ناموفق بود.", "error")
    return redirect(url_for("express_partner.plus"))
