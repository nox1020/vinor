# -*- coding: utf-8 -*-
"""پستچی وینور — گفتگوی رسمی همکار با وینور (اعلان‌ها + پیام کاربر)."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import current_app

from .notifications import (
    _normalize_user_id,
    get_user_notifications,
    mark_all_read,
    unread_count,
)

WELCOME_BODY = (
    'سلام! من پستچی وینور هستم.\n'
    'اینجا پیام‌های رسمی وینور، وضعیت همکاری و اعلان‌های مهم را می‌بینید.\n'
    'اگر سوالی دارید بنویسید؛ تیم پشتیبانی در اولین فرصت پاسخ می‌دهد.'
)


def _data_path() -> str:
    try:
        instance_path = current_app.instance_path
    except Exception:
        instance_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'instance',
        )
    data_dir = os.path.join(instance_path, 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'postchi_messages.json')


def _load_store() -> Dict[str, List[Dict[str, Any]]]:
    path = _data_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for key, value in raw.items():
        uid = _normalize_user_id(key)
        if uid and isinstance(value, list):
            out[uid] = [m for m in value if isinstance(m, dict)]
    return out


def _save_store(data: Dict[str, List[Dict[str, Any]]]) -> None:
    path = _data_path()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _user_outbound(user_id: str) -> List[Dict[str, Any]]:
    uid = _normalize_user_id(user_id)
    if not uid:
        return []
    return list(_load_store().get(uid) or [])


def _notif_as_message(notif: Dict[str, Any]) -> Dict[str, Any]:
    body = (notif.get('body') or '').strip()
    title = (notif.get('title') or '').strip()
    if title and body and title not in body:
        text = f'{title}\n{body}'
    else:
        text = body or title or 'اعلان جدید'
    return {
        'id': 'notif-' + str(notif.get('id') or uuid.uuid4().hex),
        'role': 'in',
        'body': text,
        'title': title or None,
        'action_url': (notif.get('action_url') or '').strip() or None,
        'created_at': int(notif.get('created_at') or time.time()),
        'type': (notif.get('type') or 'info'),
        'is_read': bool(notif.get('is_read')),
    }


def build_thread(user_id: str, *, limit: int = 120) -> List[Dict[str, Any]]:
    uid = _normalize_user_id(user_id)
    if not uid:
        return []

    inbound = [_notif_as_message(n) for n in get_user_notifications(uid, limit=limit)]
    outbound = []
    for m in _user_outbound(uid):
        outbound.append({
            'id': str(m.get('id') or uuid.uuid4().hex),
            'role': 'out',
            'body': (m.get('body') or '').strip(),
            'title': None,
            'action_url': None,
            'created_at': int(m.get('created_at') or time.time()),
            'type': 'user',
            'is_read': True,
        })

    thread = inbound + outbound
    thread.sort(key=lambda x: int(x.get('created_at') or 0))

    if not thread:
        thread = [{
            'id': 'welcome',
            'role': 'in',
            'body': WELCOME_BODY,
            'title': 'پستچی وینور',
            'action_url': None,
            'created_at': int(time.time()),
            'type': 'info',
            'is_read': True,
        }]
    elif not any(m.get('id') == 'welcome' for m in thread):
        # پیام خوش‌آمد فقط وقتی تاریخچه واقعی داریم در ابتدای نمایش نیست — برای UX اولین بار در preview کافی است
        pass

    return thread[-limit:]


def postchi_preview(user_id: str) -> Dict[str, Any]:
    uid = _normalize_user_id(user_id)
    if not uid:
        return {'preview': 'ورود برای مشاهده پیام‌ها', 'unread': 0, 'subtitle': 'پستچی وینور'}
    thread = build_thread(uid, limit=50)
    last = thread[-1] if thread else None
    preview = ''
    if last:
        preview = (last.get('body') or '').replace('\n', ' ').strip()
        if len(preview) > 72:
            preview = preview[:69] + '…'
    if not preview:
        preview = 'پیام‌های رسمی وینور'
    unread = unread_count(uid)
    return {
        'preview': preview,
        'unread': unread,
        'subtitle': 'پستچی وینور',
    }


def send_user_message(user_id: str, text: str) -> Optional[Dict[str, Any]]:
    uid = _normalize_user_id(user_id)
    body = (text or '').strip()
    if not uid or not body:
        return None
    if len(body) > 2000:
        body = body[:2000]

    msg = {
        'id': uuid.uuid4().hex,
        'body': body,
        'created_at': int(time.time()),
    }
    store = _load_store()
    items = store.get(uid) or []
    items.append(msg)
    store[uid] = items[-200:]
    _save_store(store)
    return {
        'id': msg['id'],
        'role': 'out',
        'body': body,
        'title': None,
        'action_url': None,
        'created_at': msg['created_at'],
        'type': 'user',
        'is_read': True,
    }


def open_postchi(user_id: str) -> int:
    """باز کردن پستچی — همه اعلان‌ها خوانده می‌شوند."""
    uid = _normalize_user_id(user_id)
    if not uid:
        return 0
    mark_all_read(uid)
    return unread_count(uid)
