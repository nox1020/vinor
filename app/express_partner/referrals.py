# -*- coding: utf-8 -*-
"""پاداش دعوت همکار: ۱ میلیون تومان به ازای هر دعوت تأییدشده."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from flask import request, session

from ..utils.share_tokens import decode_partner_ref
from ..utils.storage import (
    load_express_commissions,
    load_express_referrals,
    save_express_commissions,
    save_express_referrals,
)

REFERRAL_BONUS_AMOUNT = 1_000_000
REFERRAL_LAND_CODE = 'referral'
COMMISSION_TYPE_REFERRAL = 'referral'


def _norm(phone: str) -> str:
    return (phone or '').strip()


def _ref_from_next_url(next_url: str) -> str:
    if not next_url:
        return ''
    try:
        path = next_url if '://' in next_url else f'http://local{next_url}'
        parsed = urlparse(path)
        token = (parse_qs(parsed.query).get('ref') or [''])[0]
        return (token or '').strip()
    except Exception:
        return ''


def capture_ref_on_login() -> None:
    """نگه‌داشتن توکن ref از query یا پارامتر ref داخل next."""
    token = (request.args.get('ref') or '').strip()
    if not token:
        token = _ref_from_next_url(request.args.get('next') or session.get('next') or '')
    if token:
        session['pending_ref_token'] = token


def stash_referrer_from_request(me_phone: str) -> None:
    """ذخیره شماره معرف در سشن از ?ref= یا pending_ref_token."""
    token = (request.args.get('ref') or session.pop('pending_ref_token', None) or '').strip()
    if not token:
        return
    inviter = _norm(decode_partner_ref(token))
    me = _norm(me_phone)
    if inviter and inviter != me:
        session['referrer_phone'] = inviter


def pop_referrer_phone(me_phone: str) -> str:
    ref = _norm(session.pop('referrer_phone', None) or '')
    me = _norm(me_phone)
    if ref and ref != me:
        return ref
    return ''


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
        if int(r.get('application_id') or 0) == int(application_id):
            return
        if _norm(r.get('inviter_phone')) == inviter and _norm(r.get('invitee_phone')) == invitee:
            return
    new_id = (max([int(x.get('id', 0) or 0) for x in referrals if isinstance(x, dict)], default=0) or 0) + 1
    referrals.append({
        'id': new_id,
        'inviter_phone': inviter,
        'invitee_phone': invitee,
        'invitee_name': (invitee_name or '').strip(),
        'application_id': int(application_id),
        'status': 'pending',
        'commission_id': None,
        'created_at': datetime.utcnow().isoformat() + 'Z',
    })
    save_express_referrals(referrals)


def _find_referral_for_application(application: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    referrals = load_express_referrals() or []
    app_id = int(application.get('id') or 0)
    invitee = _norm(application.get('phone'))
    inviter = _norm(application.get('referred_by_phone'))
    for r in referrals:
        if app_id and int(r.get('application_id') or 0) == app_id:
            return r
    if inviter and invitee:
        for r in referrals:
            if _norm(r.get('inviter_phone')) == inviter and _norm(r.get('invitee_phone')) == invitee:
                return r
    return None


def _referral_commission_exists(inviter: str, invitee: str) -> bool:
    for c in load_express_commissions() or []:
        if (c.get('commission_type') or '') != COMMISSION_TYPE_REFERRAL:
            continue
        if _norm(c.get('partner_phone')) == inviter and _norm(c.get('referred_phone')) == invitee:
            return True
    return False


def grant_referral_commission_for_application(application: Dict[str, Any]) -> bool:
    """پس از تأیید درخواست همکاری توسط ادمین، پورسانت دعوت در انتظار ایجاد می‌شود."""
    inviter = _norm(application.get('referred_by_phone'))
    invitee = _norm(application.get('phone'))
    invitee_name = (application.get('name') or '').strip()
    if not inviter or not invitee or inviter == invitee:
        return False
    if _referral_commission_exists(inviter, invitee):
        return False

    referrals = load_express_referrals() or []
    ref_rec = _find_referral_for_application(application)
    if ref_rec and ref_rec.get('commission_id'):
        return False

    commissions = load_express_commissions() or []
    new_cid = (max([int(x.get('id', 0) or 0) for x in commissions if isinstance(x, dict)], default=0) or 0) + 1
    now = datetime.utcnow().isoformat() + 'Z'
    comm = {
        'id': new_cid,
        'commission_type': COMMISSION_TYPE_REFERRAL,
        'partner_phone': inviter,
        'land_code': REFERRAL_LAND_CODE,
        'sale_amount': 0,
        'commission_pct': 0,
        'commission_amount': REFERRAL_BONUS_AMOUNT,
        'referred_phone': invitee,
        'referred_name': invitee_name,
        'application_id': int(application.get('id') or 0),
        'status': 'pending',
        'created_at': now,
    }
    commissions.append(comm)
    save_express_commissions(commissions)

    try:
        from .commission_sms import notify_partner_commission_txn
        notify_partner_commission_txn(
            partner_phone=inviter,
            event='commission_pending',
            amount=REFERRAL_BONUS_AMOUNT,
            land_code=REFERRAL_LAND_CODE,
            commission_type=COMMISSION_TYPE_REFERRAL,
            reference_id=str(new_cid),
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            'referral commission_pending SMS failed inviter=%s', inviter
        )

    if ref_rec:
        ref_rec['status'] = 'approved'
        ref_rec['commission_id'] = new_cid
        ref_rec['approved_at'] = now
    else:
        rid = (max([int(x.get('id', 0) or 0) for x in referrals if isinstance(x, dict)], default=0) or 0) + 1
        referrals.append({
            'id': rid,
            'inviter_phone': inviter,
            'invitee_phone': invitee,
            'invitee_name': invitee_name,
            'application_id': int(application.get('id') or 0),
            'status': 'approved',
            'commission_id': new_cid,
            'created_at': now,
            'approved_at': now,
        })
    save_express_referrals(referrals)
    return True


def mark_referral_rejected_for_application(application: Dict[str, Any]) -> None:
    ref_rec = _find_referral_for_application(application)
    if not ref_rec:
        return
    ref_rec['status'] = 'rejected'
    ref_rec['rejected_at'] = datetime.utcnow().isoformat() + 'Z'
    referrals = load_express_referrals() or []
    save_express_referrals(referrals)


def referral_stats_for_inviter(inviter_phone: str) -> Dict[str, Any]:
    inviter = _norm(inviter_phone)
    referrals = [r for r in (load_express_referrals() or []) if _norm(r.get('inviter_phone')) == inviter]
    comms = [
        c for c in (load_express_commissions() or [])
        if _norm(c.get('partner_phone')) == inviter
        and (c.get('commission_type') or '') == COMMISSION_TYPE_REFERRAL
    ]
    invite_count = len(referrals)
    approved_count = len([r for r in referrals if r.get('status') == 'approved'])
    pending_invites = len([r for r in referrals if r.get('status') == 'pending'])
    pending_commission = sum(
        int(c.get('commission_amount') or 0)
        for c in comms
        if (c.get('status') or 'pending').strip() == 'pending'
    )
    approved_commission = sum(
        int(c.get('commission_amount') or 0)
        for c in comms
        if (c.get('status') or '').strip() == 'approved'
    )
    paid_commission = sum(
        int(c.get('commission_amount') or 0)
        for c in comms
        if (c.get('status') or '').strip() == 'paid'
    )
    return {
        'invite_count': invite_count,
        'approved_count': approved_count,
        'pending_invites': pending_invites,
        'bonus_per_invite': REFERRAL_BONUS_AMOUNT,
        'pending_commission': pending_commission,
        'approved_commission': approved_commission,
        'paid_commission': paid_commission,
    }
