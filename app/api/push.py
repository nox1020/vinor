# app/api/push.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict, Any, Iterable, Optional, Set

from flask import Blueprint, current_app, request, jsonify, session

try:
    import requests
    from requests.adapters import HTTPAdapter
except Exception:
    requests = None  # type: ignore
    HTTPAdapter = None  # type: ignore

# pywebpush>=2 — pip install pywebpush cryptography
try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    WebPushException = Exception  # type: ignore

api_push_bp = Blueprint('api_push', __name__, url_prefix='/api/push')

_PUSH_POOL_SIZE = 32
_PUSH_TIMEOUT_SEC = 3
_PUSH_TTL_SEC = 300


def _subs_path() -> str:
    base = current_app.instance_path
    path = os.path.join(base, 'data', 'push_subs.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _load_subs() -> List[Dict[str, Any]]:
    path = _subs_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _save_subs(subs: List[Dict[str, Any]]) -> None:
    path = _subs_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(subs, f, ensure_ascii=False, separators=(',', ':'))


def _normalize_sub_phone(value: Any) -> str:
    try:
        from app.services.notifications import _normalize_user_id
        return _normalize_user_id(str(value or ''))
    except Exception:
        return str(value or '').strip()


def _enrich_subscription(sub: Dict[str, Any]) -> Dict[str, Any]:
    """پیوند subscription به user_phone از سشن یا فیلد subscription."""
    phone = _normalize_sub_phone(
        session.get('user_phone') or sub.get('user_phone') or sub.get('phone') or ''
    )
    if phone and len(phone) == 11:
        sub = dict(sub)
        sub['user_phone'] = phone
    return sub


def filter_subs_for_phones(
    subs: Iterable[Dict[str, Any]],
    partner_phones: Optional[Iterable[str]],
) -> List[Dict[str, Any]]:
    """فقط subscriptionهای مرتبط با همکاران — اگر تگ user_phone وجود داشته باشد."""
    items = list(subs or [])
    if not items or not partner_phones:
        return items

    allowed: Set[str] = set()
    for raw in partner_phones:
        p = _normalize_sub_phone(raw)
        if p and len(p) == 11:
            allowed.add(p)
    if not allowed:
        return items

    tagged = [
        s for s in items
        if _normalize_sub_phone(s.get('user_phone') or s.get('phone') or '') in allowed
    ]
    if tagged:
        return tagged

    # سازگاری عقب‌رو: subscription قدیمی بدون user_phone
    has_any_tag = any(s.get('user_phone') or s.get('phone') for s in items)
    return items if not has_any_tag else tagged


def _make_push_session():
    if requests is None or HTTPAdapter is None:
        return None
    sess = requests.Session()
    adapter = HTTPAdapter(pool_connections=_PUSH_POOL_SIZE, pool_maxsize=_PUSH_POOL_SIZE, max_retries=0)
    sess.mount('https://', adapter)
    sess.mount('http://', adapter)
    return sess


@dataclass
class _PushBatchContext:
    data_str: str
    vapid_private: str
    vapid_claims: Dict[str, str]
    http_session: Any
    timeout: int = _PUSH_TIMEOUT_SEC


def _build_push_context(payload: Dict[str, Any]) -> Optional[_PushBatchContext]:
    if webpush is None:
        return None
    vapid_private = current_app.config.get('VAPID_PRIVATE_KEY', '')
    if not vapid_private:
        return None
    return _PushBatchContext(
        data_str=json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
        vapid_private=vapid_private,
        vapid_claims={'sub': current_app.config.get('VAPID_SUB') or 'mailto:admin@vinor.ir'},
        http_session=_make_push_session(),
        timeout=_PUSH_TIMEOUT_SEC,
    )


def _send_one(subscription: Dict[str, Any], payload: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    ctx = _build_push_context(payload)
    if ctx is None:
        if webpush is None:
            return {'ok': False, 'error': 'PYWEBPUSH_NOT_INSTALLED', 'remove': False}
        return {'ok': False, 'error': 'MISSING_VAPID_PRIVATE_KEY', 'remove': False}
    ctx.timeout = max(2, min(int(timeout or 10), 15))
    return _send_one_fast(ctx, subscription)


def _send_one_fast(ctx: _PushBatchContext, subscription: Dict[str, Any]) -> Dict[str, Any]:
    if webpush is None:
        return {'ok': False, 'error': 'PYWEBPUSH_NOT_INSTALLED', 'remove': False}
    try:
        webpush(
            subscription_info=subscription,
            data=ctx.data_str,
            vapid_private_key=ctx.vapid_private,
            vapid_claims=ctx.vapid_claims,
            timeout=ctx.timeout,
            ttl=_PUSH_TTL_SEC,
            headers={'Urgency': 'high'},
            requests_session=ctx.http_session,
        )
        return {'ok': True}
    except WebPushException as e:
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        # 403 is the usual VAPID key-mismatch after a key rotation.
        if status in (403, 404, 410):
            return {'ok': False, 'error': f'STATUS_{status}', 'remove': True}
        return {'ok': False, 'error': str(e), 'remove': False}
    except Exception as e:
        return {'ok': False, 'error': str(e), 'remove': False}


def _run_push_batch(
    app,
    payload: Dict[str, Any],
    subs_snapshot: List[Dict[str, Any]],
    broadcast_id: Optional[str] = None,
) -> None:
    with app.app_context():
        ctx = _build_push_context(payload)
        if ctx is None:
            return

        to_remove: Set[str] = set()
        push_sent = 0
        push_failed = 0

        workers = min(_PUSH_POOL_SIZE, max(4, len(subs_snapshot)))

        def _send(sub: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
            return sub, _send_one_fast(ctx, sub)

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_send, s) for s in subs_snapshot]
                for fut in as_completed(futures):
                    try:
                        sub, res = fut.result()
                    except Exception:
                        push_failed += 1
                        continue
                    if res.get('ok'):
                        push_sent += 1
                    elif res.get('remove'):
                        ep = sub.get('endpoint')
                        if ep:
                            to_remove.add(ep)
                    else:
                        push_failed += 1

            if to_remove:
                current = _load_subs() or []
                current = [s for s in current if s.get('endpoint') not in to_remove]
                _save_subs(current)

            if broadcast_id:
                try:
                    from app.services.notification_history import update_broadcast_push_stats
                    update_broadcast_push_stats(broadcast_id, push_sent, push_failed)
                except Exception:
                    pass

            try:
                app.logger.info(
                    f"Push broadcast done: sent={push_sent}, failed={push_failed}, "
                    f"removed={len(to_remove)}, subs={len(subs_snapshot)}"
                )
            except Exception:
                pass
        except Exception as e:
            try:
                app.logger.error(f"Push broadcast failed: {e}", exc_info=True)
            except Exception:
                pass
        finally:
            try:
                if ctx.http_session is not None:
                    ctx.http_session.close()
            except Exception:
                pass


def send_push_batch_background(
    payload: Dict[str, Any],
    subs: List[Dict[str, Any]] | None = None,
    *,
    target_phones: Optional[List[str]] = None,
    broadcast_id: Optional[str] = None,
) -> int:
    """ارسال Web Push در پس‌زمینه. تعداد subscriber هدف را برمی‌گرداند."""
    app = current_app._get_current_object()
    all_subs = list(subs) if subs is not None else list(_load_subs() or [])
    subs_snapshot = filter_subs_for_phones(all_subs, target_phones)
    if not subs_snapshot or not app.config.get('VAPID_PRIVATE_KEY'):
        return 0

    threading.Thread(
        target=_run_push_batch,
        args=(app, payload, subs_snapshot, broadcast_id),
        daemon=True,
        name=f'vinor-push-{broadcast_id[:8] if broadcast_id else "batch"}',
    ).start()
    return len(subs_snapshot)


@api_push_bp.get('/config')
def push_config():
    return jsonify({'publicKey': current_app.config.get('VAPID_PUBLIC_KEY', '')})


@api_push_bp.post('/subscribe')
def subscribe():
    try:
        sub = request.get_json(force=True, silent=False)
    except Exception:
        return jsonify({'ok': False, 'error': 'INVALID_JSON'}), 400

    if not isinstance(sub, dict) or 'endpoint' not in sub:
        return jsonify({'ok': False, 'error': 'INVALID_SUBSCRIPTION'}), 400

    sub = _enrich_subscription(sub)
    subs = _load_subs()
    endpoint = sub.get('endpoint')

    idx = next((i for i, s in enumerate(subs) if s.get('endpoint') == endpoint), None)
    if idx is not None:
        subs[idx] = sub
    else:
        subs.append(sub)

    _save_subs(subs)
    return jsonify({'ok': True, 'count': len(subs), 'tagged': bool(sub.get('user_phone'))})


@api_push_bp.post('/unsubscribe')
def unsubscribe():
    data = request.get_json(force=True, silent=True) or {}
    endpoint = data.get('endpoint')
    if not endpoint:
        return jsonify({'ok': False, 'error': 'MISSING_ENDPOINT'}), 400

    subs = _load_subs()
    subs = [s for s in subs if s.get('endpoint') != endpoint]
    _save_subs(subs)
    return jsonify({'ok': True, 'count': len(subs)})


@api_push_bp.get('/subs')
def list_subs():
    subs = _load_subs()
    tagged = sum(1 for s in subs if s.get('user_phone'))
    return jsonify({'ok': True, 'count': len(subs), 'tagged': tagged})


push_bp = api_push_bp
__all__ = [
    'api_push_bp', 'push_bp', '_load_subs', '_save_subs', '_send_one',
    'send_push_batch_background', 'filter_subs_for_phones',
]
