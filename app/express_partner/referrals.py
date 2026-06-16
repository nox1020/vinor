# -*- coding: utf-8 -*-
"""پاداش دعوت همکار — جریان: لینک → درخواست همکاری → تأیید ادمین → پورسانت خودکار در موجودی."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from flask import request, session

from ..utils.share_tokens import decode_partner_ref
from ..utils.storage import (
    load_express_commissions,
    load_express_partners,
    load_express_referrals,
    save_express_commissions,
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


def _norm(phone: str) -> str:
    return (phone or "").strip()


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


def capture_ref_on_login() -> None:
    token = (request.args.get("ref") or "").strip()
    if not token:
        token = _ref_from_next_url(request.args.get("next") or session.get("next") or "")
    if token:
        session["pending_ref_token"] = token


def stash_referrer_from_request(me_phone: str) -> None:
    token = (request.args.get("ref") or session.pop("pending_ref_token", None) or "").strip()
    if not token:
        return
    inviter = _norm(decode_partner_ref(token))
    me = _norm(me_phone)
    if inviter and inviter != me:
        session["referrer_phone"] = inviter


def pop_referrer_phone(me_phone: str) -> str:
    ref = _norm(session.pop("referrer_phone", None) or "")
    me = _norm(me_phone)
    if ref and ref != me:
        return ref
    return ""


def register_referral_on_application(
    *,
    inviter_phone: str,
    invitee_phone: str,
    invitee_name: str,
    application_id: int,
) -> None:
    inviter = _norm(inviter_phone)
    invitee = _norm(invitee_phone)
    if not inviter or not invitee or inviter == invitee:
        return
    referrals = load_express_referrals() or []
    for r in referrals:
        if int(r.get("application_id") or 0) == int(application_id):
            return
        if _norm(r.get("inviter_phone")) == inviter and _norm(r.get("invitee_phone")) == invitee:
            return
    new_id = (max([int(x.get("id", 0) or 0) for x in referrals if isinstance(x, dict)], default=0) or 0) + 1
    referrals.append(
        {
            "id": new_id,
            "inviter_phone": inviter,
            "invitee_phone": invitee,
            "invitee_name": (invitee_name or "").strip(),
            "application_id": int(application_id),
            "status": REF_INVITE_PENDING,
            "commission_id": None,
            "created_at": _now_iso(),
        }
    )
    save_express_referrals(referrals)


def _find_referral_for_application(
    application: Dict[str, Any],
    referrals: Optional[list] = None,
) -> Optional[Dict[str, Any]]:
    refs = referrals if referrals is not None else (load_express_referrals() or [])
    app_id = int(application.get("id") or 0)
    invitee = _norm(application.get("phone"))
    inviter = _norm(application.get("referred_by_phone"))
    for r in refs:
        if app_id and int(r.get("application_id") or 0) == app_id:
            return r
    if inviter and invitee:
        for r in refs:
            if _norm(r.get("inviter_phone")) == inviter and _norm(r.get("invitee_phone")) == invitee:
                return r
    return None


def _active_referral_commission_exists(inviter: str, invitee: str) -> bool:
    for c in load_express_commissions() or []:
        if (c.get("commission_type") or "") != COMMISSION_TYPE_REFERRAL:
            continue
        if _norm(c.get("partner_phone")) != inviter:
            continue
        if _norm(c.get("referred_phone")) != invitee:
            continue
        if (str(c.get("status") or "pending")).strip() in ACTIVE_COMMISSION_STATUSES:
            return True
    return False


def _resolve_inviter_invitee(
    application: Dict[str, Any], ref_rec: Optional[Dict[str, Any]]
) -> tuple:
    inviter = _norm(application.get("referred_by_phone")) or _norm((ref_rec or {}).get("inviter_phone"))
    invitee = _norm(application.get("phone")) or _norm((ref_rec or {}).get("invitee_phone"))
    invitee_name = (application.get("name") or (ref_rec or {}).get("invitee_name") or "").strip()
    return inviter, invitee, invitee_name


def _credit_inviter_partner_income(inviter_phone: str, amount: int) -> None:
    inviter = _norm(inviter_phone)
    if not inviter or amount <= 0:
        return
    partners = load_express_partners() or []
    for p in partners:
        if _norm(p.get("phone")) == inviter:
            current_income = int(p.get("total_income", 0) or 0)
            p["total_income"] = current_income + amount
            p["last_updated"] = _now_iso()
            break
    save_express_partners(partners)


def grant_referral_commission_for_application(application: Dict[str, Any]) -> bool:
    referrals = load_express_referrals() or []
    ref_rec = _find_referral_for_application(application, referrals)
    inviter, invitee, invitee_name = _resolve_inviter_invitee(application, ref_rec)

    if not inviter or not invitee or inviter == invitee:
        return False
    if _active_referral_commission_exists(inviter, invitee):
        return False
    if ref_rec and ref_rec.get("commission_id"):
        return False

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
    return True


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
    inviter = _norm(inviter_phone)
    referrals = [r for r in (load_express_referrals() or []) if _norm(r.get("inviter_phone")) == inviter]
    comms = [
        c
        for c in (load_express_commissions() or [])
        if _norm(c.get("partner_phone")) == inviter
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
