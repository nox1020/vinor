"""پیامک «اقدام لازم در پنل ادمین» — یک نقطه برای همهٔ صف‌های داشبورد."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from flask import current_app

from app.services.sms import (
    send_sms_direct,
    normalize_iran_mobile,
    is_valid_iran_mobile,
    sms_is_infrastructure_error,
)
from app.services.sms_config import get_sms_line_number
from app.utils.storage import load_settings, load_sms_history, save_sms_history


def _format_toman(amount: int) -> str:
    v = max(0, int(amount or 0))
    if v == 0:
        return '0'
    return f'{v:,}'.replace(',', '،')


def _append_history(entry: dict) -> None:
    try:
        history = load_sms_history(current_app) or []
        entry = dict(entry)
        entry['id'] = len(history) + 1
        history.append(entry)
        if len(history) > 10000:
            history = history[-10000:]
        save_sms_history(history, current_app)
    except Exception as exc:
        try:
            current_app.logger.error('Admin action SMS history save failed: %s', exc)
        except Exception:
            pass


def _build_message(action: str, settings: dict, **kw: Any) -> str:
    name = (kw.get('partner_name') or '').strip() or (kw.get('partner_phone') or '').strip() or 'همکار'
    phone = (kw.get('partner_phone') or '').strip()

    if action == 'application':
        custom = (settings.get('partner_application_admin_sms_message') or '').strip()
        if custom:
            return (
                custom.replace('{name}', name)
                .replace('{phone}', phone)
                .replace('{partner_name}', name)
                .replace('{partner_phone}', phone)
            )
        return f'وینور — درخواست همکاری جدید\n{name}\n{phone}'

    if action == 'withdrawal':
        bank = (kw.get('bank_summary') or '').strip() or '—'
        amt = _format_toman(int(kw.get('amount') or 0))
        return (
            f'وینور — درخواست برداشت (اقدام)\n'
            f'همکار: {name}\n'
            f'موبایل: {phone}\n'
            f'مبلغ: {amt} تومان\n'
            f'حساب: {bank}'
        )

    if action == 'visit':
        title = (kw.get('land_title') or '').strip() or str(kw.get('land_code') or '—')
        code = str(kw.get('land_code') or '—')
        vdate = (kw.get('visit_date') or '').strip() or '—'
        return (
            f'وینور — درخواست بازدید (اقدام)\n'
            f'همکار: {name}\n'
            f'موبایل: {phone}\n'
            f'فایل: {title} ({code})\n'
            f'تاریخ: {vdate}'
        )

    if action == 'commission':
        code = str(kw.get('land_code') or '—')
        amt = _format_toman(int(kw.get('amount') or 0))
        return (
            f'وینور — پورسانت در انتظار تأیید\n'
            f'همکار: {name}\n'
            f'موبایل: {phone}\n'
            f'فایل: {code}\n'
            f'مبلغ: {amt} تومان'
        )

    if action == 'ticket':
        subj = (kw.get('subject') or '').strip() or 'تیکت پشتیبانی'
        preview = (kw.get('detail') or kw.get('message') or '').strip()
        if len(preview) > 80:
            preview = preview[:80] + '…'
        lines = [
            'وینور — تیکت پشتیبانی جدید',
            f'همکار: {name}',
            f'موبایل: {phone}',
            f'موضوع: {subj}',
        ]
        if preview:
            lines.append(f'متن: {preview}')
        return '\n'.join(lines)

    detail = (kw.get('detail') or '').strip()
    return f'وینور — مورد جدید در صف اقدام ادمین\n{detail or name}'


def notify_admin_pending_action(action: str, **kwargs: Any) -> dict:
    """
    بلافاصله پس از ایجاد هر مورد در صف اقدام داشبورد ادمین، پیامک به شمارهٔ تنظیمات.
    action: application | withdrawal | visit | commission | ticket
    """
    settings = load_settings(current_app) or {}
    admin_phone = normalize_iran_mobile(
        str(settings.get('partner_application_admin_phone') or '09121471301')
    )
    line = (settings.get('sms_line_number') or get_sms_line_number() or '300089930616').strip()

    if not is_valid_iran_mobile(admin_phone):
        try:
            current_app.logger.warning(
                'Admin action SMS skipped: invalid admin phone action=%s raw=%r',
                action,
                settings.get('partner_application_admin_phone'),
            )
        except Exception:
            pass
        return {'ok': False, 'skipped': True, 'error': 'invalid_admin_phone'}

    msg = _build_message(action, settings, **kwargs)
    sms_result = send_sms_direct(mobile=admin_phone, message=msg, line_number=line)
    ok = bool(sms_result.get('ok'))
    err = None
    body = sms_result.get('body') or {}

    if not ok:
        err = str(body.get('message') or body.get('error') or 'sms_send_failed')
        if sms_is_infrastructure_error(err):
            time.sleep(0.6)
            sms_result = send_sms_direct(mobile=admin_phone, message=msg, line_number=line)
            ok = bool(sms_result.get('ok'))
            body = sms_result.get('body') or {}
            if ok:
                err = None
            else:
                err = str(body.get('message') or body.get('error') or err)

    if not ok:
        try:
            current_app.logger.error(
                'Admin action SMS failed action=%s admin=%s status=%s body=%s',
                action,
                admin_phone,
                sms_result.get('status'),
                body,
            )
        except Exception:
            pass

    _append_history({
        'mobile': admin_phone,
        'recipient_name': 'admin',
        'message': msg,
        'parameters': {'action': action, **{k: v for k, v in kwargs.items() if v is not None}},
        'success': ok,
        'status_code': sms_result.get('status', 0),
        'response': body,
        'source': f'admin_pending_action_{action}',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'error': None if ok else err,
    })

    return {'ok': ok, 'skipped': False, 'error': err}
