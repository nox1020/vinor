# -*- coding: utf-8 -*-
"""ارسال FCM به APK (حتی وقتی اپ بسته است)."""
from __future__ import annotations

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from flask import current_app

from app.services.firebase_config import ensure_firebase_ready, get_service_account, get_firebase_status
from app.services.fcm_tokens import tokens_for_phones, unregister_token

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_token_cache: Dict[str, Any] = {"access_token": None, "expires_at": 0}
_token_lock = threading.Lock()


def is_fcm_configured() -> bool:
    try:
        return bool(ensure_firebase_ready().get("send_ready"))
    except Exception:
        return False


def _load_service_account():
    cached = current_app.config.get("FCM_SERVICE_ACCOUNT")
    if isinstance(cached, dict) and cached.get("private_key"):
        return cached
    return get_service_account()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _service_account_jwt(sa: Dict[str, Any]) -> str:
    """JWT برای OAuth2 service account — فقط cryptography (بدون google-auth)."""
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    claims = {
        "iss": sa["client_email"],
        "scope": _FCM_SCOPE,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    private_key = serialization.load_pem_private_key(
        sa["private_key"].encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(signature)}"


def _access_token() -> Optional[str]:
    now = time.time()
    with _token_lock:
        if _token_cache.get("access_token") and (_token_cache.get("expires_at") or 0) > now + 60:
            return _token_cache["access_token"]

        sa = _load_service_account()
        if not sa or not sa.get("private_key") or not sa.get("client_email"):
            return None

        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                jwt = _service_account_jwt(sa)
                resp = requests.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": jwt,
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"OAuth token HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                token = data.get("access_token")
                if not token:
                    raise RuntimeError("OAuth response missing access_token")
                expires_in = int(data.get("expires_in") or 3600)
                _token_cache["access_token"] = token
                _token_cache["expires_at"] = now + max(expires_in - 60, 300)
                return token
            except Exception as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))

        try:
            current_app.logger.error(f"FCM OAuth token failed: {last_err}")
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
            # notification → سینی سیستم وقتی اپ بسته است (Android خودکار نشان می‌دهد)
            "notification": {
                "title": str(title or "وینور").strip()[:120],
                "body": str(body or "").strip()[:500],
            },
            "data": {
                "title": str(title or "وینور").strip()[:120],
                "body": str(body or "").strip()[:500],
                "url": url or "/express/partner/notifications",
            },
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "vinor_express_partner",
                    "notification_priority": "PRIORITY_HIGH",
                    "default_sound": True,
                    "default_vibrate_timings": True,
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
                if code == "UNREGISTERED":
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
    app = current_app._get_current_object()

    def _send_one(tok: str) -> Dict[str, Any]:
        with app.app_context():
            ensure_firebase_ready(app)
            return send_fcm_to_token(tok, title=title, body=body, url=url)

    workers = min(16, max(2, len(tokens)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_send_one, tok): tok for tok in tokens}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res.get("ok"):
                    sent += 1
                else:
                    failed += 1
                    try:
                        err = str(res.get("error") or "")[:400]
                        if err:
                            current_app.logger.warning(
                                "FCM send failed token=%s… error=%s",
                                futures[fut][:12],
                                err,
                            )
                    except Exception:
                        pass
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
                ensure_firebase_ready(app)
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
    broadcast_id: Optional[str] = None,
) -> None:
    if not phones:
        return
    app = current_app._get_current_object()
    target_url = url or "/express/partner/notifications"
    phone_list = list(phones)
    bid = (broadcast_id or "").strip() or None

    def _worker() -> None:
        with app.app_context():
            try:
                ensure_firebase_ready(app)
                token_targets = len(tokens_for_phones(phone_list))
                if not is_fcm_configured():
                    app.logger.warning("FCM batch skipped — not configured")
                    if bid:
                        from app.services.notification_history import update_broadcast_push_stats
                        update_broadcast_push_stats(bid, 0, token_targets)
                    return
                res = send_fcm_to_phones(phone_list, title=title, body=body, url=target_url)
                app.logger.info(f"FCM batch push: {res}")
                if bid:
                    from app.services.notification_history import update_broadcast_push_stats
                    update_broadcast_push_stats(
                        bid,
                        int(res.get("sent") or 0),
                        int(res.get("failed") or 0),
                    )
            except Exception as e:
                try:
                    app.logger.error(f"FCM batch push failed: {e}", exc_info=True)
                    if bid:
                        from app.services.notification_history import update_broadcast_push_stats
                        update_broadcast_push_stats(bid, 0, len(tokens_for_phones(phone_list)))
                except Exception:
                    pass

    threading.Thread(target=_worker, daemon=True, name="vinor-fcm-batch").start()
