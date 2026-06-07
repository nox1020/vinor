# -*- coding: utf-8 -*-
"""تیکت پشتیبانی همکاران."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..utils.dates import format_iso_date_jalali

OPEN_STATUS = 'open'
IN_PROGRESS_STATUS = 'in_progress'
ANSWERED_STATUS = 'answered'
CLOSED_STATUS = 'closed'

OPEN_STATUSES = frozenset({OPEN_STATUS, IN_PROGRESS_STATUS})
ADMIN_STATUSES = frozenset({OPEN_STATUS, IN_PROGRESS_STATUS, ANSWERED_STATUS, CLOSED_STATUS})

SUBJECT_MAX_LEN = 120
MESSAGE_MAX_LEN = 2000
MESSAGE_MIN_LEN = 10
MAX_OPEN_TICKETS_PER_USER = 3
MAX_TICKETS_PER_DAY = 5
MIN_TICKET_INTERVAL_SECONDS = 120
DUPLICATE_WINDOW_SECONDS = 600

TICKET_CATEGORIES: Dict[str, str] = {
    'account': 'حساب کاربری',
    'financial': 'مالی و پورسانت',
    'technical': 'فنی و باگ',
    'cooperation': 'همکاری',
    'other': 'سایر',
}

STATUS_LABELS: Dict[str, str] = {
    OPEN_STATUS: 'جدید',
    IN_PROGRESS_STATUS: 'در حال بررسی',
    ANSWERED_STATUS: 'پاسخ داده شد',
    CLOSED_STATUS: 'بسته شده',
}

_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + 'Z'


def _tehran_today() -> datetime.date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Asia/Tehran')).date()
    except Exception:
        return datetime.utcnow().date()


def _parse_iso_ts(raw: Any) -> Optional[datetime]:
    s = (str(raw or '')).strip()
    if not s:
        return None
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _sanitize_ticket_text(text: str, *, max_len: int) -> str:
    s = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    s = _CONTROL_CHARS_RE.sub('', s)
    s = _HTML_TAG_RE.sub('', s)
    s = s.strip()
    if max_len > 0:
        s = s[:max_len]
    return s


def _message_fingerprint(message: str) -> str:
    return ' '.join((message or '').casefold().split())


def _user_tickets(tickets: List[Dict[str, Any]], phone: str) -> List[Dict[str, Any]]:
    ph = (phone or '').strip()
    if not ph:
        return []
    return [
        r for r in (tickets or [])
        if isinstance(r, dict) and str(r.get('user_phone') or '').strip() == ph
    ]


def _open_ticket_count(tickets: List[Dict[str, Any]], phone: str) -> int:
    return sum(
        1 for r in _user_tickets(tickets, phone)
        if (str(r.get('status') or '')).strip() in OPEN_STATUSES
    )


def _tickets_created_today(tickets: List[Dict[str, Any]], phone: str) -> int:
    today = _tehran_today()
    count = 0
    for row in _user_tickets(tickets, phone):
        created = _parse_iso_ts(row.get('created_at'))
        if created and created.date() == today:
            count += 1
    return count


def _seconds_until_next_ticket(tickets: List[Dict[str, Any]], phone: str) -> int:
    latest: Optional[datetime] = None
    for row in _user_tickets(tickets, phone):
        created = _parse_iso_ts(row.get('created_at'))
        if created and (latest is None or created > latest):
            latest = created
    if not latest:
        return 0
    elapsed = (datetime.utcnow() - latest).total_seconds()
    remaining = MIN_TICKET_INTERVAL_SECONDS - elapsed
    return max(0, int(remaining) + 1)


def _has_recent_duplicate(
    tickets: List[Dict[str, Any]],
    phone: str,
    message: str,
) -> bool:
    fp = _message_fingerprint(message)
    if not fp:
        return False
    cutoff = datetime.utcnow() - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
    for row in _user_tickets(tickets, phone):
        created = _parse_iso_ts(row.get('created_at'))
        if not created or created < cutoff:
            continue
        prev = _sanitize_ticket_text(str(row.get('message') or ''), max_len=MESSAGE_MAX_LEN)
        if _message_fingerprint(prev) == fp:
            return True
    return False


def _format_ticket_date(iso: Any) -> str:
    s = (str(iso or '')).strip()
    if not s:
        return ''
    return format_iso_date_jalali(s[:10])


def partner_ticket_stats(
    tickets: List[Dict[str, Any]],
    phone: str,
) -> Dict[str, Any]:
    ph = (phone or '').strip()
    open_count = _open_ticket_count(tickets, ph)
    daily_used = _tickets_created_today(tickets, ph)
    cooldown = _seconds_until_next_ticket(tickets, ph)
    daily_remaining = max(0, MAX_TICKETS_PER_DAY - daily_used)
    open_remaining = max(0, MAX_OPEN_TICKETS_PER_USER - open_count)
    can_submit = (
        bool(ph)
        and open_count < MAX_OPEN_TICKETS_PER_USER
        and daily_used < MAX_TICKETS_PER_DAY
        and cooldown <= 0
    )
    block_reason = ''
    if ph and not can_submit:
        if open_count >= MAX_OPEN_TICKETS_PER_USER:
            block_reason = 'open_limit'
        elif daily_used >= MAX_TICKETS_PER_DAY:
            block_reason = 'daily_limit'
        elif cooldown > 0:
            block_reason = 'cooldown'
    return {
        'open_count': open_count,
        'total_count': len(_user_tickets(tickets, ph)),
        'daily_used': daily_used,
        'daily_remaining': daily_remaining,
        'open_remaining': open_remaining,
        'cooldown_seconds': cooldown,
        'can_submit': can_submit,
        'block_reason': block_reason,
    }


def partner_ticket_error_message(
    err: str,
    tickets: List[Dict[str, Any]],
    phone: str,
) -> str:
    if err == 'empty_message':
        return 'متن تیکت را بنویسید.'
    if err == 'message_too_short':
        return f'متن تیکت باید حداقل {MESSAGE_MIN_LEN} کاراکتر باشد.'
    if err == 'too_many_open':
        return (
            f'حداکثر {MAX_OPEN_TICKETS_PER_USER} تیکت باز همزمان مجاز است. '
            'ابتدا منتظر پاسخ بمانید یا تیکت‌های قبلی را ببندید.'
        )
    if err == 'daily_limit':
        return f'امروز به سقف {MAX_TICKETS_PER_DAY} تیکت رسیده‌اید. فردا دوباره تلاش کنید.'
    if err == 'rate_limited':
        wait = _seconds_until_next_ticket(tickets, phone)
        return f'لطفاً {wait} ثانیه صبر کنید و دوباره تلاش کنید.'
    if err == 'duplicate_message':
        return 'این متن را همین اخیراً ارسال کرده‌اید. لطفاً کمی صبر کنید یا متن دیگری بنویسید.'
    if err == 'unauthorized':
        return 'برای ارسال تیکت ابتدا وارد حساب خود شوید.'
    return 'ارسال تیکت ناموفق بود. دوباره تلاش کنید.'


def _find_ticket(tickets: List[Dict[str, Any]], ticket_id: str) -> Optional[Dict[str, Any]]:
    tid = (ticket_id or '').strip()
    if not tid:
        return None
    for row in tickets:
        if isinstance(row, dict) and str(row.get('id') or '') == tid:
            return row
    return None


def tickets_for_phone(
    tickets: List[Dict[str, Any]],
    phone: str,
    *,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    ph = (phone or '').strip()
    if not ph:
        return []
    rows = _user_tickets(tickets, ph)
    rows.sort(key=lambda r: str(r.get('created_at') or ''), reverse=True)
    if limit > 0:
        rows = rows[:limit]
    return [user_row_dict(r) for r in rows]


def create_support_ticket(
    tickets: List[Dict[str, Any]],
    *,
    user_phone: str,
    user_name: str,
    category: str,
    subject: str,
    message: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    ph = (user_phone or '').strip()
    if not ph:
        return None, 'unauthorized'

    cat = (category or 'other').strip()
    if cat not in TICKET_CATEGORIES:
        cat = 'other'

    subj = _sanitize_ticket_text(subject, max_len=SUBJECT_MAX_LEN)
    body = _sanitize_ticket_text(message, max_len=MESSAGE_MAX_LEN)

    if not body:
        return None, 'empty_message'
    if len(body) < MESSAGE_MIN_LEN:
        return None, 'message_too_short'

    if _open_ticket_count(tickets, ph) >= MAX_OPEN_TICKETS_PER_USER:
        return None, 'too_many_open'
    if _tickets_created_today(tickets, ph) >= MAX_TICKETS_PER_DAY:
        return None, 'daily_limit'
    if _seconds_until_next_ticket(tickets, ph) > 0:
        return None, 'rate_limited'
    if _has_recent_duplicate(tickets, ph, body):
        return None, 'duplicate_message'

    if not subj:
        subj = TICKET_CATEGORIES.get(cat, 'سایر')

    now_iso = _now_iso()
    rec: Dict[str, Any] = {
        'id': uuid.uuid4().hex[:16],
        'user_phone': ph,
        'user_name': _sanitize_ticket_text(user_name, max_len=80) or ph,
        'category': cat,
        'subject': subj,
        'message': body,
        'status': OPEN_STATUS,
        'admin_reply': '',
        'created_at': now_iso,
        'updated_at': now_iso,
    }
    tickets.append(rec)
    return rec, None


def admin_update_support_ticket(
    tickets: List[Dict[str, Any]],
    ticket_id: str,
    *,
    new_status: str,
    admin_reply: str | None = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    target = (new_status or '').strip()
    if target not in ADMIN_STATUSES:
        return None, 'invalid_status'
    rec = _find_ticket(tickets, ticket_id)
    if not rec:
        return None, 'not_found'

    current = (str(rec.get('status') or OPEN_STATUS)).strip()
    reply = (admin_reply if admin_reply is not None else None)
    reply_changed = False
    if reply is not None:
        new_reply = _sanitize_ticket_text(reply, max_len=MESSAGE_MAX_LEN)
        prev_reply = (str(rec.get('admin_reply') or '')).strip()
        if new_reply != prev_reply:
            if new_reply:
                rec['admin_reply'] = new_reply
            else:
                rec.pop('admin_reply', None)
            reply_changed = True
            if new_reply and target == OPEN_STATUS:
                target = ANSWERED_STATUS

    if current == target and not reply_changed:
        return rec, 'unchanged'

    now_iso = _now_iso()
    rec['status'] = target
    rec['updated_at'] = now_iso
    if reply_changed and rec.get('admin_reply'):
        rec['replied_at'] = now_iso
    if target == CLOSED_STATUS:
        rec['closed_at'] = now_iso
    elif target != CLOSED_STATUS:
        rec.pop('closed_at', None)
    return rec, None


def user_row_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    st = (str(row.get('status') or OPEN_STATUS)).strip()
    cat = (str(row.get('category') or 'other')).strip()
    msg = row.get('message') or ''
    reply = row.get('admin_reply') or ''
    created = row.get('created_at') or ''
    preview = msg.replace('\n', ' ').strip()
    if len(preview) > 88:
        preview = preview[:88].rstrip() + '…'
    return {
        'id': row.get('id'),
        'category': cat,
        'category_label': TICKET_CATEGORIES.get(cat, cat),
        'subject': row.get('subject') or '',
        'message': msg,
        'message_preview': preview,
        'status': st,
        'status_label': STATUS_LABELS.get(st, st),
        'admin_reply': reply,
        'has_reply': bool((str(reply)).strip()),
        'is_open': st in OPEN_STATUSES,
        'created_at': created,
        'created_at_jalali': _format_ticket_date(created),
        'updated_at': row.get('updated_at') or '',
        'replied_at': row.get('replied_at') or '',
        'replied_at_jalali': _format_ticket_date(row.get('replied_at') or ''),
    }


def admin_row_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    data = user_row_dict(row)
    data.update({
        'user_phone': row.get('user_phone') or '',
        'user_name': row.get('user_name') or '',
    })
    return data
