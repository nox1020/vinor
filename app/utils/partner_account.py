"""حذف کامل داده‌های همکار اکسپرس."""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict

from flask import current_app


def _norm_phone(phone: str) -> str:
    from ..services.notifications import _normalize_user_id

    return _normalize_user_id(phone or '')


def _phone_row_matches(row: Dict[str, Any], phone: str, *fields: str) -> bool:
    ph = _norm_phone(phone)
    if not ph or not isinstance(row, dict):
        return False
    for field in fields:
        if _norm_phone(str(row.get(field) or '')) == ph:
            return True
    return False


def _filter_not_phone(items: list, phone: str, *fields: str) -> list:
    ph = _norm_phone(phone)
    if not ph:
        return items
    out = []
    for row in items:
        if isinstance(row, dict) and _phone_row_matches(row, ph, *fields):
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
        load_support_tickets,
        save_support_tickets,
        load_express_visit_requests,
        save_express_visit_requests,
        load_partner_withdrawals,
        save_partner_withdrawals,
    )

    ph = _norm_phone(phone)
    if not ph:
        return {'ok': False, 'errors': ['missing_phone']}

    errors: list[str] = []

    try:
        partners = load_express_partners() or []
        save_express_partners(
            [p for p in partners if not _phone_row_matches(p, ph, 'phone')]
        )
    except Exception:
        current_app.logger.error('purge: partners failed', exc_info=True)
        errors.append('partners')

    try:
        apps = load_express_partner_apps() or []
        save_express_partner_apps(
            [a for a in apps if not _phone_row_matches(a, ph, 'phone')]
        )
    except Exception:
        current_app.logger.error('purge: apps failed', exc_info=True)
        errors.append('apps')

    try:
        assignments = load_express_assignments() or []
        kept = [a for a in assignments if not _phone_row_matches(a, ph, 'partner_phone')]
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

    try:
        tickets = load_support_tickets() or []
        save_support_tickets(_filter_not_phone(tickets, ph, 'user_phone'))
    except Exception:
        current_app.logger.error('purge: support tickets failed', exc_info=True)
        errors.append('support_tickets')

    try:
        visits = load_express_visit_requests() or []
        save_express_visit_requests(_filter_not_phone(visits, ph, 'partner_phone'))
    except Exception:
        current_app.logger.error('purge: visit requests failed', exc_info=True)
        errors.append('visit_requests')

    try:
        withdrawals = load_partner_withdrawals() or []
        save_partner_withdrawals(_filter_not_phone(withdrawals, ph, 'partner_phone'))
    except Exception:
        current_app.logger.error('purge: withdrawals failed', exc_info=True)
        errors.append('withdrawals')

    _delete_avatar_dir(ph)

    return {'ok': not errors, 'errors': errors}


def admin_purge_person_account(phone: str) -> dict[str, Any]:
    """حذف کامل حساب کاربر/همکار از پنل ادمین."""
    from ..utils.storage import (
        load_consults,
        save_consults,
        load_notifications,
        save_notifications,
        load_users,
        save_users,
    )

    ph = _norm_phone(phone)
    if not ph:
        return {'ok': False, 'errors': ['missing_phone']}

    errors: list[str] = list((purge_partner_account(ph).get('errors') or []))

    try:
        users = load_users() or []
        save_users([
            u for u in users
            if isinstance(u, dict) and not _phone_row_matches(u, ph, 'phone', 'mobile', 'id', 'user_id')
        ])
    except Exception:
        current_app.logger.error('purge: users failed', exc_info=True)
        errors.append('users')

    try:
        consults = load_consults() or []
        save_consults(_filter_not_phone(consults, ph, 'phone'))
    except Exception:
        current_app.logger.error('purge: consults failed', exc_info=True)
        errors.append('consults')

    try:
        notes_data = load_notifications() or {}
        if isinstance(notes_data, dict):
            keys = [k for k in notes_data if _norm_phone(k) == ph]
            for key in keys:
                notes_data.pop(key, None)
            save_notifications(notes_data)
    except Exception:
        current_app.logger.error('purge: notifications failed', exc_info=True)
        errors.append('notifications')

    return {'ok': not errors, 'errors': errors}
