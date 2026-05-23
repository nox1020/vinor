"""حذف کامل داده‌های همکار اکسپرس."""
from __future__ import annotations

import os
import shutil
from typing import Any

from flask import current_app


def _norm_phone(phone: str) -> str:
    return (phone or '').strip()


def _filter_not_phone(items: list, phone: str, *fields: str) -> list:
    ph = _norm_phone(phone)
    if not ph:
        return items
    out = []
    for row in items:
        if not isinstance(row, dict):
            out.append(row)
            continue
        if any(_norm_phone(str(row.get(f) or '')) == ph for f in fields):
            continue
        out.append(row)
    return out


def _clear_transaction_holder(assignments: list, phone: str) -> list:
    ph = _norm_phone(phone)
    if not ph:
        return assignments
    for a in assignments:
        if not isinstance(a, dict):
            continue
        if _norm_phone(str(a.get('transaction_holder') or '')) != ph:
            continue
        a.pop('transaction_holder', None)
        a.pop('transaction_started_at', None)
        if (a.get('status') or '').strip() == 'in_transaction':
            a['status'] = 'active'
    return assignments


def _delete_avatar_dir(phone: str) -> None:
    ph = _norm_phone(phone)
    if not ph:
        return
    try:
        base = os.path.join(
            current_app.instance_path, 'data', 'uploads', 'partner', 'avatars', ph
        )
        if os.path.isdir(base):
            shutil.rmtree(base, ignore_errors=True)
    except Exception:
        current_app.logger.warning('Failed to remove partner avatar dir for %s', ph, exc_info=True)


def purge_partner_account(phone: str) -> dict[str, Any]:
    """
    حذف رکورد پروفایل و داده‌های وابسته همکار.
    برمی‌گرداند: {'ok': bool, 'errors': [...]}
    """
    from ..utils.storage import (
        load_express_assignments,
        save_express_assignments,
        load_express_commissions,
        save_express_commissions,
        load_express_partner_apps,
        save_express_partner_apps,
        load_express_partners,
        save_express_partners,
        load_express_reposts,
        save_express_reposts,
        load_express_referrals,
        save_express_referrals,
        load_partner_bank_accounts,
        save_partner_bank_accounts,
        load_partner_files_meta,
        save_partner_files_meta,
        load_partner_notes,
        save_partner_notes,
        load_partner_routines,
        save_partner_routines,
        load_partner_sales,
        save_partner_sales,
    )

    ph = _norm_phone(phone)
    if not ph:
        return {'ok': False, 'errors': ['missing_phone']}

    errors: list[str] = []

    try:
        partners = load_express_partners() or []
        save_express_partners(
            [p for p in partners if _norm_phone(str(p.get('phone') or '')) != ph]
        )
    except Exception:
        current_app.logger.error('purge: partners failed', exc_info=True)
        errors.append('partners')

    try:
        apps = load_express_partner_apps() or []
        save_express_partner_apps(
            [a for a in apps if _norm_phone(str(a.get('phone') or '')) != ph]
        )
    except Exception:
        current_app.logger.error('purge: apps failed', exc_info=True)
        errors.append('apps')

    try:
        assignments = load_express_assignments() or []
        kept = [a for a in assignments if _norm_phone(str(a.get('partner_phone') or '')) != ph]
        kept = _clear_transaction_holder(kept, ph)
        save_express_assignments(kept)
    except Exception:
        current_app.logger.error('purge: assignments failed', exc_info=True)
        errors.append('assignments')

    try:
        commissions = load_express_commissions() or []
        save_express_commissions(_filter_not_phone(
            commissions, ph, 'partner_phone', 'referred_phone'
        ))
    except Exception:
        current_app.logger.error('purge: commissions failed', exc_info=True)
        errors.append('commissions')

    try:
        notes = load_partner_notes() or []
        save_partner_notes(_filter_not_phone(notes, ph, 'phone'))
    except Exception:
        current_app.logger.error('purge: notes failed', exc_info=True)
        errors.append('notes')

    try:
        reposts = load_express_reposts() or []
        save_express_reposts(_filter_not_phone(reposts, ph, 'partner_phone'))
    except Exception:
        current_app.logger.error('purge: reposts failed', exc_info=True)
        errors.append('reposts')

    try:
        banks = load_partner_bank_accounts() or []
        save_partner_bank_accounts(_filter_not_phone(banks, ph, 'phone'))
    except Exception:
        current_app.logger.error('purge: bank accounts failed', exc_info=True)
        errors.append('bank_accounts')

    try:
        routines = load_partner_routines() or []
        save_partner_routines(_filter_not_phone(routines, ph, 'phone'))
    except Exception:
        current_app.logger.error('purge: routines failed', exc_info=True)
        errors.append('routines')

    try:
        metas = load_partner_files_meta() or []
        save_partner_files_meta(_filter_not_phone(metas, ph, 'phone'))
    except Exception:
        current_app.logger.error('purge: files meta failed', exc_info=True)
        errors.append('files_meta')

    try:
        sales = load_partner_sales() or []
        save_partner_sales(_filter_not_phone(sales, ph, 'phone', 'partner_phone'))
    except Exception:
        current_app.logger.error('purge: sales failed', exc_info=True)
        errors.append('sales')

    try:
        referrals = load_express_referrals() or []
        save_express_referrals(_filter_not_phone(
            referrals, ph, 'inviter_phone', 'invitee_phone'
        ))
    except Exception:
        current_app.logger.error('purge: referrals failed', exc_info=True)
        errors.append('referrals')

    _delete_avatar_dir(ph)

    return {'ok': not errors, 'errors': errors}
