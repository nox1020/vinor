# -*- coding: utf-8 -*-
"""پاداش دعوت همکار — جریان: لینک → درخواست همکاری → تأیید ادمین → پورسانت خودکار در موجودی."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from flask import request, session

from ..utils.share_tokens import decode_partner_ref
from ..utils.storage import (
    load_express_commissions,
    load_express_partner_apps,
    load_express_partners,
    load_express_referrals,
    save_express_commissions,
    save_express_partner_apps,
    save_express_partners,
    save_express_referrals,
)
from .commissions_flow import ACTIVE_COMMISSION_STATUSES

REFERRAL_BONUS_AMOUNT = 500_000
REFERRAL_LAND_CODE = "referral"
COMMISSION_TYPE_REFERRAL = "referral"

REF_INVITE_PENDING = "pending"
REF_COMMISSION_PENDING = "commission_pending"
REF_COMMISSION_APPROVED = "commission_approved"
REF_REJECTED = "rejected"

REF_COOKIE_NAME = "vinor_ref"
REF_COOKIE_MAX_AGE = 7 * 24 * 3600
_APPROVED_PARTNER_STATUSES = frozenset({"approved", "active", "enabled", "ok", "true", "1"})


def _normalize_phone(phone: str) -> str:
    from ..services.notifications import _normalize_user_id

    return _normalize_user_id(phone or "")


def _norm(phone: str) -> str:
    """نرمال شماره — برای سازگاری با فراخوانی‌های قبلی."""
    return _normalize_phone(phone)


def _phones_match(a: str, b: str) -> bool:
    na, nb = _normalize_phone(a), _normalize_phone(b)
    return bool(na and nb and na == nb)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _ref_from_next_url(next_url: str) -> str:
    if not next_url:
        return ""
    try:
        path = next_url if "://" in next_url else f"http://local{next_url}"
        parsed = urlparse(path)
        token = (parse_qs(parsed.query).get("ref") or [""])[0]
        return (token or "").strip()
    except Exception:
        return ""


def _inviter_from_ref_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    decoded = decode_partner_ref(token)
    if not decoded:
        return ""
    return _normalize_phone(decoded)


def _store_ref_token(token: str) -> None:
    token = (token or "").strip()
    if not token:
        return
    session["pending_ref_token"] = token
    inviter = _inviter_from_ref_token(token)
    if inviter:
        session["referrer_phone"] = inviter


def set_ref_cookie_on_response(response, token: str):
    """پشتیبان ref در کوکی — برای WebView/سشن ناپایدار."""
    token = (token or "").strip()
    if not token or response is None:
        return response
    try:
        response.set_cookie(
            REF_COOKIE_NAME,
            token,
            max_age=REF_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=bool(getattr(request, "is_secure", False)),
        )
    except Exception:
        pass
    return response


def clear_ref_cookie_on_response(response):
    if response is None:
        return response
    try:
        response.delete_cookie(REF_COOKIE_NAME)
    except Exception:
        pass
    return response


def _ref_token_candidates(*, form_ref: str = "", query_ref: str = "") -> List[str]:
    seen: set = set()
    out: List[str] = []
    for raw in (
        (query_ref or "").strip(),
        (form_ref or "").strip(),
        (session.get("pending_ref_token") or "").strip(),
        (request.cookies.get(REF_COOKIE_NAME) or "").strip(),
    ):
        if raw and raw not in seen:
            seen.add(raw)
            out.append(raw)
    return out


def _inviter_is_approved_partner(inviter_phone: str) -> bool:
    inviter = _normalize_phone(inviter_phone)
    if not inviter:
        return False
    for p in load_express_partners() or []:
        if not isinstance(p, dict) or not _phones_match(p.get("phone"), inviter):
            continue
        if p.get("status") is True:
            return True
        st = str(p.get("status") or "").strip().lower()
        return st in _APPROVED_PARTNER_STATUSES
    return False


def store_referral_ref_token(token: str) -> None:
    _store_ref_token(token)


def capture_ref_on_login() -> None:
    token = (request.args.get("ref") or "").strip()
    if not token:
        token = _ref_from_next_url(request.args.get("next") or session.get("next") or "")
    _store_ref_token(token)


def stash_referrer_from_request(me_phone: str) -> None:
    token = (request.args.get("ref") or session.get("pending_ref_token") or "").strip()
    if token:
        _store_ref_token(token)
        return
    inviter = _normalize_phone(session.get("referrer_phone") or "")
    me = _normalize_phone(me_phone)
    if inviter and inviter != me:
        session["referrer_phone"] = inviter


def referral_ref_token_for_session() -> str:
    return (session.get("pending_ref_token") or "").strip()


def resolve_referrer_for_apply(
    me_phone: str,
    *,
    form_ref: str = "",
    query_ref: str = "",
) -> str:
    me = _normalize_phone(me_phone)
    for token in _ref_token_candidates(form_ref=form_ref, query_ref=query_ref):
        inviter = _inviter_from_ref_token(token)
        if inviter and inviter != me and _inviter_is_approved_partner(inviter):
            session["referrer_phone"] = inviter
            session["pending_ref_token"] = token
            return inviter
    inviter = _normalize_phone(session.get("referrer_phone") or "")
    if inviter and inviter != me and _inviter_is_approved_partner(inviter):
        return inviter
    return ""


def attach_referrer_to_pending_application(
    invitee_phone: str,
    *,
    form_ref: str = "",
    query_ref: str = "",
) -> bool:
    """اگر درخواست همکاری قبلاً ثبت شده ولی معرف ندارد، ref فعلی را وصل کن."""
    inviter = resolve_referrer_for_apply(
        invitee_phone,
        form_ref=form_ref,
        query_ref=query_ref,
    )
    if not inviter:
        return False

    apps = load_express_partner_apps() or []
    changed = False
    for app in apps:
        if not isinstance(app, dict):
            continue
        if not _phones_match(app.get("phone"), invitee_phone):
            continue
        st = str(app.get("status") or "").strip().lower()
        if st in ("approved", "rejected", "cancelled"):
            continue
        existing = _normalize_phone(app.get("referred_by_phone") or "")
        if existing:
            if existing == inviter:
                return True
            continue
        app["referred_by_phone"] = inviter
        changed = True
        app_id = int(app.get("id") or 0)
        if app_id:
            register_referral_on_application(
                inviter_phone=inviter,
                invitee_phone=_normalize_phone(app.get("phone") or invitee_phone),
                invitee_name=(app.get("name") or "").strip(),
                application_id=app_id,
            )
    if changed:
        save_express_partner_apps(apps)
    return changed


def clear_referrer_session() -> None:
    session.pop("pending_ref_token", None)
    session.pop("referrer_phone", None)


def pop_referrer_phone(me_phone: str) -> str:
    return resolve_referrer_for_apply(me_phone)


def _referral_commission_is_active(commission_id: Any) -> bool:
    try:
        cid = int(commission_id or 0)
    except Exception:
        return False
    if not cid:
        return False
    for c in load_express_commissions() or []:
        if int(c.get("id") or 0) != cid:
            continue
        return (str(c.get("status") or "pending")).strip() in ACTIVE_COMMISSION_STATUSES
    return False


def _referral_pair_can_register_again(r: Dict[str, Any]) -> bool:
    """دعوت ردشده یا بدون پورسانت فعال — برای درخواست جدید همان جفت."""
    if _referral_commission_is_active(r.get("commission_id")):
        return False
    st = (str(r.get("status") or "")).strip()
    return st in (REF_REJECTED, REF_INVITE_PENDING, "pending", "", REF_COMMISSION_PENDING)


def register_referral_on_application(
    *,
    inviter_phone: str,
    invitee_phone: str,
    invitee_name: str,
    application_id: int,
) -> None:
    inviter = _normalize_phone(inviter_phone)
    invitee = _normalize_phone(invitee_phone)
    if not inviter or not invitee or inviter == invitee:
        return
    referrals = load_express_referrals() or []
    app_id = int(application_id or 0)
    for r in referrals:
        if int(r.get("application_id") or 0) == app_id:
            return
    for r in referrals:
        if not _phones_match(r.get("inviter_phone"), inviter):
            continue
        if not _phones_match(r.get("invitee_phone"), invitee):
            continue
        if _referral_commission_is_active(r.get("commission_id")):
            return
        if _referral_pair_can_register_again(r):
            r["application_id"] = app_id
            r["status"] = REF_INVITE_PENDING
            r["invitee_name"] = (invitee_name or r.get("invitee_name") or "").strip()
            r.pop("commission_id", None)
            r.pop("commission_created_at", None)
            r.pop("commission_approved_at", None)
            r.pop("rejected_at", None)
            save_express_referrals(referrals)
        return
    new_id = (max([int(x.get("id", 0) or 0) for x in referrals if isinstance(x, dict)], default=0) or 0) + 1
    referrals.append(
        {
            "id": new_id,
            "inviter_phone": inviter,
            "invitee_phone": invitee,
            "invitee_name": (invitee_name or "").strip(),
            "application_id": app_id,
            "status": REF_INVITE_PENDING,
            "commission_id": None,
            "created_at": _now_iso(),
        }
    )
    save_express_referrals(referrals)


def ensure_referral_record_for_application(application: Dict[str, Any]) -> None:
    """اگر درخواست معرف دارد ولی ردیف referral نیست، قبل از grant بساز."""
    inviter = _normalize_phone(application.get("referred_by_phone") or "")
    invitee = _normalize_phone(application.get("phone") or "")
    if not inviter or not invitee or inviter == invitee:
        return
    app_id = int(application.get("id") or 0)
    if not app_id:
        return
    if _find_referral_for_application(application):
        return
    register_referral_on_application(
        inviter_phone=inviter,
        invitee_phone=invitee,
        invitee_name=(application.get("name") or "").strip(),
        application_id=app_id,
    )


def _find_referral_for_application(
    application: Dict[str, Any],
    referrals: Optional[list] = None,
) -> Optional[Dict[str, Any]]:
    refs = referrals if referrals is not None else (load_express_referrals() or [])
    app_id = int(application.get("id") or 0)
    invitee = _normalize_phone(application.get("phone"))
    inviter = _normalize_phone(application.get("referred_by_phone"))
    for r in refs:
        if app_id and int(r.get("application_id") or 0) == app_id:
            return r
    if inviter and invitee:
        for r in refs:
            if _phones_match(r.get("inviter_phone"), inviter) and _phones_match(r.get("invitee_phone"), invitee):
                return r
    return None


def _active_referral_commission_exists(inviter: str, invitee: str) -> bool:
    inv = _normalize_phone(inviter)
    invt = _normalize_phone(invitee)
    for c in load_express_commissions() or []:
        if (c.get("commission_type") or "") != COMMISSION_TYPE_REFERRAL:
            continue
        if not _phones_match(c.get("partner_phone"), inv):
            continue
        if not _phones_match(c.get("referred_phone"), invt):
            continue
        if (str(c.get("status") or "pending")).strip() in ACTIVE_COMMISSION_STATUSES:
            return True
    return False


def _resolve_inviter_invitee(
    application: Dict[str, Any], ref_rec: Optional[Dict[str, Any]]
) -> tuple:
    inviter = _normalize_phone(application.get("referred_by_phone")) or _normalize_phone((ref_rec or {}).get("inviter_phone"))
    invitee = _normalize_phone(application.get("phone")) or _normalize_phone((ref_rec or {}).get("invitee_phone"))
    invitee_name = (application.get("name") or (ref_rec or {}).get("invitee_name") or "").strip()
    return inviter, invitee, invitee_name


def _credit_inviter_partner_income(inviter_phone: str, amount: int) -> None:
    inviter = _normalize_phone(inviter_phone)
    if not inviter or amount <= 0:
        return
    partners = load_express_partners() or []
    for p in partners:
        if _phones_match(p.get("phone"), inviter):
            current_income = int(p.get("total_income", 0) or 0)
            p["total_income"] = current_income + amount
            p["last_updated"] = _now_iso()
            if _normalize_phone(str(p.get("phone") or "")) != inviter:
                p["phone"] = inviter
            break
    save_express_partners(partners)


REFERRAL_GRANT_REASONS_FA = {
    "invalid_phones": "شماره معرف یا دعوت‌شده نامعتبر است.",
    "inviter_not_partner": "معرف در فهرست همکاران تأییدشده نیست.",
    "duplicate_commission": "پورسانت دعوت این جفت قبلاً ثبت شده است.",
    "existing_commission": "رکورد دعوت قبلاً به پورسانت وصل شده است.",
    "no_referrer": "معرف برای این همکار ثبت نشده است.",
}


def grant_referral_commission_for_application(
    application: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    import logging

    log = logging.getLogger(__name__)
    ensure_referral_record_for_application(application)
    referrals = load_express_referrals() or []
    ref_rec = _find_referral_for_application(application, referrals)
    inviter, invitee, invitee_name = _resolve_inviter_invitee(application, ref_rec)

    if not inviter or not invitee or inviter == invitee:
        log.warning(
            "referral grant skipped: invalid phones inviter=%r invitee=%r app_id=%s",
            inviter,
            invitee,
            application.get("id"),
        )
        return False, "invalid_phones"
    if not _inviter_is_approved_partner(inviter):
        log.warning(
            "referral grant skipped: inviter not approved partner inviter=%s app_id=%s",
            inviter,
            application.get("id"),
        )
        return False, "inviter_not_partner"
    if _active_referral_commission_exists(inviter, invitee):
        log.info(
            "referral grant skipped: commission already exists inviter=%s invitee=%s",
            inviter,
            invitee,
        )
        return False, "duplicate_commission"
    if ref_rec and ref_rec.get("commission_id"):
        if _referral_commission_is_active(ref_rec.get("commission_id")):
            log.info(
                "referral grant skipped: referral record already has active commission_id=%s",
                ref_rec.get("commission_id"),
            )
            return False, "existing_commission"
        ref_rec.pop("commission_id", None)
        ref_rec.pop("commission_created_at", None)
        ref_rec.pop("commission_approved_at", None)
        if (str(ref_rec.get("status") or "")).strip() == REF_REJECTED:
            ref_rec["status"] = REF_INVITE_PENDING
            ref_rec.pop("rejected_at", None)

    commissions = load_express_commissions() or []
    new_cid = (max([int(x.get("id", 0) or 0) for x in commissions if isinstance(x, dict)], default=0) or 0) + 1
    now = _now_iso()
    comm = {
        "id": new_cid,
        "commission_type": COMMISSION_TYPE_REFERRAL,
        "partner_phone": inviter,
        "land_code": REFERRAL_LAND_CODE,
        "sale_amount": 0,
        "commission_pct": 0,
        "commission_amount": REFERRAL_BONUS_AMOUNT,
        "referred_phone": invitee,
        "referred_name": invitee_name,
        "application_id": int(application.get("id") or 0),
        "status": "approved",
        "created_at": now,
        "approved_at": now,
    }
    commissions.append(comm)
    save_express_commissions(commissions)

    try:
        _credit_inviter_partner_income(inviter, REFERRAL_BONUS_AMOUNT)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "referral commission income credit failed inviter=%s", inviter
        )

    try:
        from .commission_sms import notify_partner_commission_txn

        notify_partner_commission_txn(
            partner_phone=inviter,
            event="commission_approved",
            amount=REFERRAL_BONUS_AMOUNT,
            land_code=REFERRAL_LAND_CODE,
            commission_type=COMMISSION_TYPE_REFERRAL,
            reference_id=str(new_cid),
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "referral commission_approved SMS failed inviter=%s", inviter
        )

    if ref_rec:
        ref_rec["status"] = REF_COMMISSION_APPROVED
        ref_rec["commission_id"] = new_cid
        ref_rec["commission_created_at"] = now
        ref_rec["commission_approved_at"] = now
    else:
        rid = (max([int(x.get("id", 0) or 0) for x in referrals if isinstance(x, dict)], default=0) or 0) + 1
        referrals.append(
            {
                "id": rid,
                "inviter_phone": inviter,
                "invitee_phone": invitee,
                "invitee_name": invitee_name,
                "application_id": int(application.get("id") or 0),
                "status": REF_COMMISSION_APPROVED,
                "commission_id": new_cid,
                "created_at": now,
                "commission_created_at": now,
                "commission_approved_at": now,
            }
        )
    save_express_referrals(referrals)
    return True, None


def grant_referral_for_partner_record(partner: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """ثبت دستی/مجدد پورسانت دعوت برای همکار تأییدشده."""
    inviter = _normalize_phone(partner.get("referred_by_phone") or "")
    invitee = _normalize_phone(partner.get("phone") or "")
    if not inviter:
        return False, "no_referrer"
    application = {
        "id": int(partner.get("referral_application_id") or 0),
        "phone": invitee,
        "name": (partner.get("name") or "").strip(),
        "referred_by_phone": inviter,
    }
    ok, reason = grant_referral_commission_for_application(application)
    if ok:
        partner.pop("referral_grant_pending", None)
    return ok, reason


def mark_referral_rejected_for_application(application: Dict[str, Any]) -> None:
    referrals = load_express_referrals() or []
    ref_rec = _find_referral_for_application(application, referrals)
    if not ref_rec:
        return
    ref_rec["status"] = REF_REJECTED
    ref_rec["rejected_at"] = _now_iso()
    save_express_referrals(referrals)


def sync_referral_on_commission_status(commission: Dict[str, Any]) -> None:
    if (commission.get("commission_type") or "") != COMMISSION_TYPE_REFERRAL:
        return
    cid = int(commission.get("id") or 0)
    if not cid:
        return
    st = (str(commission.get("status") or "")).strip()
    referrals = load_express_referrals() or []
    ref_rec = None
    for r in referrals:
        if int(r.get("commission_id") or 0) == cid:
            ref_rec = r
            break
    if not ref_rec:
        return
    now = _now_iso()
    if st == "approved":
        ref_rec["status"] = REF_COMMISSION_APPROVED
        ref_rec["commission_approved_at"] = now
    elif st == "paid":
        ref_rec["status"] = REF_COMMISSION_APPROVED
        ref_rec["paid_at"] = now
    elif st == "rejected":
        ref_rec["status"] = REF_REJECTED
        ref_rec["rejected_at"] = now
        ref_rec.pop("commission_id", None)
    save_express_referrals(referrals)


def _referral_invite_pending(r: Dict[str, Any]) -> bool:
    st = (str(r.get("status") or "")).strip()
    return st in (REF_INVITE_PENDING, "pending", "")


def referral_stats_for_inviter(inviter_phone: str) -> Dict[str, Any]:
    inviter = _normalize_phone(inviter_phone)
    referrals = [
        r for r in (load_express_referrals() or [])
        if _phones_match(r.get("inviter_phone"), inviter)
    ]
    comms = [
        c
        for c in (load_express_commissions() or [])
        if _phones_match(c.get("partner_phone"), inviter)
        and (c.get("commission_type") or "") == COMMISSION_TYPE_REFERRAL
    ]

    waiting_invites = len([r for r in referrals if _referral_invite_pending(r)])
    pending_commission = sum(
        int(c.get("commission_amount") or 0)
        for c in comms
        if (c.get("status") or "pending").strip() == "pending"
    )
    in_balance = sum(
        int(c.get("commission_amount") or 0)
        for c in comms
        if (c.get("status") or "").strip() == "approved"
    )
    paid_commission = sum(
        int(c.get("commission_amount") or 0)
        for c in comms
        if (c.get("status") or "").strip() == "paid"
    )
    successful_invites = len(
        [
            r
            for r in referrals
            if (str(r.get("status") or "")).strip()
            in (REF_COMMISSION_PENDING, REF_COMMISSION_APPROVED, "approved", "commission_pending")
        ]
    )

    return {
        "invite_count": len(referrals),
        "waiting_invites": waiting_invites,
        "successful_invites": successful_invites,
        "approved_count": successful_invites,
        "pending_invites": waiting_invites,
        "bonus_per_invite": REFERRAL_BONUS_AMOUNT,
        "pending_commission": pending_commission,
        "approved_commission": in_balance,
        "in_balance": in_balance,
        "paid_commission": paid_commission,
        "total_earned": in_balance + paid_commission,
    }
