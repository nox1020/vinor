# -*- coding: utf-8 -*-
"""ارسال FCM به APK (حتی وقتی اپ بسته است)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from flask import current_app

from app.services.firebase_config import get_service_account, get_firebase_status
from app.services.fcm_tokens import tokens_for_phones, unregister_token

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_token_cache: Dict[str, Any] = {"access_token": None, "expires_at": 0}


def is_fcm_configured() -> bool:
    try:
        return bool(get_firebase_status().get("send_ready"))
    except Exception:
        return False


def _load_service_account():
    cached = current_app.config.get("FCM_SERVICE_ACCOUNT")
    if isinstance(cached, dict) and cached.get("private_key"):
        return cached
    return get_service_account()


def _access_token() -> Optional[str]:
    import time
    now = time.time()
    if _token_cache.get("access_token") and (_token_cache.get("expires_at") or 0) > now + 60:
        return _token_cache["access_token"]

    sa = _load_service_account()
    if not sa:
        return None
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleAuthRequest

        creds = service_account.Credentials.from_service_account_info(sa, scopes=[_FCM_SCOPE])
        creds.refresh(GoogleAuthRequest())
        _token_cache["access_token"] = creds.token
        _token_cache["expires_at"] = now + 3300
        return creds.token
    except Exception as e:
        try:
            current_app.logger.error(f"FCM OAuth token failed: {e}")
        except Exception:
            pass
        return None


def _project_id() -> Optional[str]:
    sa = _load_service_account()
    if sa:
        pid = (sa.get("project_id") or "").strip()
        if pid:
            return pid
    try:
        return (get_firebase_status().get("project_id") or "").strip() or None
    except Exception:
        return None


def send_fcm_to_token(
    token: str,
    *,
    title: str,
    body: str,
    url: str = "/express/partner/notifications",
) -> Dict[str, Any]:
    if not token:
        return {"ok": False, "error": "NO_TOKEN"}
    if not is_fcm_configured():
        return {"ok": False, "error": "FCM_NOT_CONFIGURED"}

    access = _access_token()
    project = _project_id()
    if not access or not project:
        return {"ok": False, "error": "FCM_AUTH_FAILED"}

    payload = {
        "message": {
            "token": token,
            "notification": {
                "title": str(title or "وینور").strip()[:120],
                "body": str(body or "").strip()[:500],
            },
            "data": {
                "title": str(title or "وینور").strip()[:120],
                "body": str(body or "").strip()[:500],
                "url": url or "/express/partner/notifications",
                "click_action": "OPEN_NOTIFICATIONS",
            },
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": "vinor_express_partner",
                    "click_action": "OPEN_NOTIFICATIONS",
                    "notification_priority": "PRIORITY_HIGH",
                },
            },
        }
    }

    endpoint = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    try:
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {access}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=payload,
            timeout=8,
        )
        if resp.status_code == 200:
            return {"ok": True}
        err_body = resp.text[:500]
        remove = False
        try:
            err_json = resp.json()
            details = (((err_json.get("error") or {}).get("details")) or [])
            for d in details:
                code = (d.get("errorCode") or "").upper()
                if code in ("UNREGISTERED", "INVALID_ARGUMENT"):
                    remove = True
        except Exception:
            pass
        if resp.status_code in (404, 410):
            remove = True
        if remove:
            unregister_token(token)
        return {"ok": False, "error": err_body, "remove": remove}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_fcm_to_phones(
    phones: List[str],
    *,
    title: str,
    body: str,
    url: str = "/express/partner/notifications",
) -> Dict[str, int]:
    tokens = tokens_for_phones(phones)
    if not tokens:
        return {"sent": 0, "failed": 0, "skipped": len(phones), "targets": 0}
    sent = 0
    failed = 0
    workers = min(16, max(2, len(tokens)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(send_fcm_to_token, tok, title=title, body=body, url=url): tok
            for tok in tokens
        }
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res.get("ok"):
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
    return {"sent": sent, "failed": failed, "targets": len(tokens)}


def send_fcm_to_user_background(
    phone: str,
    *,
    title: str,
    body: str,
    url: Optional[str] = None,
) -> None:
    if not is_fcm_configured():
        return
    app = current_app._get_current_object()
    target_url = url or "/express/partner/notifications"

    def _worker() -> None:
        with app.app_context():
            try:
                res = send_fcm_to_phones([phone], title=title, body=body, url=target_url)
                if res.get("sent") or res.get("failed"):
                    app.logger.info(f"FCM user push phone={phone}: {res}")
            except Exception as e:
                try:
                    app.logger.error(f"FCM user push failed: {e}", exc_info=True)
                except Exception:
                    pass

    threading.Thread(target=_worker, daemon=True, name="vinor-fcm-user").start()


def send_fcm_batch_background(
    phones: List[str],
    *,
    title: str,
    body: str,
    url: Optional[str] = None,
) -> None:
    if not is_fcm_configured() or not phones:
        return
    app = current_app._get_current_object()
    target_url = url or "/express/partner/notifications"
    phone_list = list(phones)

    def _worker() -> None:
        with app.app_context():
            try:
                res = send_fcm_to_phones(phone_list, title=title, body=body, url=target_url)
                app.logger.info(f"FCM batch push: {res}")
            except Exception as e:
                try:
                    app.logger.error(f"FCM batch push failed: {e}", exc_info=True)
                except Exception:
                    pass

    threading.Thread(target=_worker, daemon=True, name="vinor-fcm-batch").start()
