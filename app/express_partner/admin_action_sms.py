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
        return f'وینور\nهمکاری جدید\n{name}\n{phone}'

    if action == 'withdrawal':
        bank = (kw.get('bank_summary') or '').strip()
        amt = _format_toman(int(kw.get('amount') or 0))
        msg = f'وینور\nبرداشت {amt} تومن\n{name} · {phone}'
        if bank:
            msg += f'\n{bank}'
        return msg

    if action == 'visit':
        code = str(kw.get('land_code') or '—')
        vdate = (kw.get('visit_date') or '').strip()
        msg = f'وینور\nبازدید جدید · {code}\n{name} · {phone}'
        if vdate and vdate != '—':
            msg += f'\n{vdate}'
        return msg

    if action == 'visit_schedule':
        # درخواست تعیین وقت بازدید از مدال خانه → پیامک پشتیبان
        lines = ['وینور', 'درخواست تعیین وقت بازدید', name]
        notes = (kw.get('notes') or '').strip()
        if notes:
            lines.append(notes)
        sys_date = (kw.get('system_date') or '').strip()
        if sys_date:
            lines.append(sys_date)
        if phone:
            lines.append(phone)
        return '\n'.join(lines)

    if action == 'visit_done':
        code = str(kw.get('land_code') or '—')
        return f'وینور\nانجام بازدید · {code}\n{name} · {phone}'

    if action == 'commission':
        code = str(kw.get('land_code') or '—')
        amt = _format_toman(int(kw.get('amount') or 0))
        return f'وینور\nپورسانت {amt} تومن · {code}\n{name} · {phone}'

    # vinor_plus: مسیر اصلی plus_checkout + زرین‌پال؛ SMS فقط fallback
    if action == 'vinor_plus':
        return f'وینور\nدرخواست پلاس\n{name}\n{phone}'

    detail = (kw.get('detail') or '').strip()
    return f'وینور\nاقدام لازم\n{detail or name}'


def _send_sms_to(mobile: str, msg: str, *, line: str, action: str, recipient_name: str, **kwargs: Any) -> dict:
    sms_result = send_sms_direct(mobile=mobile, message=msg, line_number=line, record_history=False)
    ok = bool(sms_result.get('ok'))
    err = None
    body = sms_result.get('body') or {}

    if not ok:
        err = str(body.get('message') or body.get('error') or 'sms_send_failed')
        if sms_is_infrastructure_error(err):
            time.sleep(0.6)
            sms_result = send_sms_direct(mobile=mobile, message=msg, line_number=line, record_history=False)
            ok = bool(sms_result.get('ok'))
            body = sms_result.get('body') or {}
            if ok:
                err = None
            else:
                err = str(body.get('message') or body.get('error') or err)

    if not ok:
        try:
            current_app.logger.error(
                'Admin action SMS failed action=%s mobile=%s status=%s body=%s',
                action,
                mobile,
                sms_result.get('status'),
                body,
            )
        except Exception:
            pass

    _append_history({
        'mobile': mobile,
        'recipient_name': recipient_name,
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


def _notify_special_land_owner(action: str, msg: str, line: str, **kwargs: Any) -> None:
    """برای بازدید روی آگهی ویژه، علاوه بر ادمین به مالک ویژه هم پیامک بزن."""
    if action not in ('visit', 'visit_done'):
        return
    land_code = str(kwargs.get('land_code') or '').strip()
    if not land_code:
        return
    try:
        from app.express_partner.partner_roles import partner_is_special
        from app.utils.storage import load_ads_cached, load_express_partners
        lands = load_ads_cached() or []
        land = next((l for l in lands if isinstance(l, dict) and str(l.get('code')) == land_code), None)
        if not land:
            return
        owner = normalize_iran_mobile(str(land.get('owner') or '').strip())
        if not is_valid_iran_mobile(owner):
            return
        partners = load_express_partners() or []
        profile = next(
            (
                p for p in partners
                if isinstance(p, dict)
                and normalize_iran_mobile(str(p.get('phone') or '')) == owner
            ),
            None,
        )
        if not partner_is_special(profile):
            return
        owner_msg = msg
        if action == 'visit':
            owner_msg = (
                f"وینور\nبازدید جدید روی آگهی‌ت · {land_code}\n"
                f"نهایی شد — از صندوق بازدید ببین"
            )
        elif action == 'visit_done':
            owner_msg = (
                f"وینور\nانجام بازدید روی آگهی‌ت · {land_code}\n"
                f"از صندوق بازدید تأیید کن"
            )
        _send_sms_to(
            owner,
            owner_msg,
            line=line,
            action=action,
            recipient_name='special_owner',
            **kwargs,
        )
    except Exception:
        try:
            current_app.logger.exception(
                'special owner visit SMS failed action=%s land=%s', action, land_code
            )
        except Exception:
            pass


def notify_admin_pending_action(action: str, **kwargs: Any) -> dict:
    """
    بلافاصله پس از ایجاد هر مورد در صف اقدام داشبورد ادمین، پیامک به شمارهٔ تنظیمات.
    action: application | withdrawal | visit | visit_schedule | commission
    """
    settings = load_settings(current_app) or {}
    admin_phone = normalize_iran_mobile(
        str(settings.get('partner_application_admin_phone') or '09121471301')
    )
    line = (settings.get('sms_line_number') or get_sms_line_number() or '09981801922').strip()

    if not is_valid_iran_mobile(admin_phone):
        try:
            current_app.logger.warning(
                'Admin action SMS skipped: invalid admin phone action=%s raw=%r',
                action,
                settings.get('partner_application_admin_phone'),
            )
        except Exception:
            pass
        # هنوز به ویژه اطلاع بده اگر لازم باشد
        try:
            msg = _build_message(action, settings, **kwargs)
            _notify_special_land_owner(action, msg, line, **kwargs)
        except Exception:
            pass
        return {'ok': False, 'skipped': True, 'error': 'invalid_admin_phone'}

    msg = _build_message(action, settings, **kwargs)
    result = _send_sms_to(
        admin_phone,
        msg,
        line=line,
        action=action,
        recipient_name='admin',
        **kwargs,
    )
    try:
        _notify_special_land_owner(action, msg, line, **kwargs)
    except Exception:
        pass
    return result
