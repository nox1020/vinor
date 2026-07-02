# -*- coding: utf-8 -*-
"""ذخیره FCM tokenهای دستگاه همکاران."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from flask import current_app

MAX_TOKENS_PER_USER = 5


def _tokens_path() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "instance")
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "fcm_tokens.json")


def _normalize_phone(phone: str) -> str:
    from app.services.notifications import _normalize_user_id
    return _normalize_user_id(phone or "")


def _load_all() -> Dict[str, List[Dict[str, Any]]]:
    path = _tokens_path()
    if not os.path.exists(path):
        return {}
    try:
        if os.path.getsize(path) == 0:
            return {}
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return {
                str(k): [x for x in v if isinstance(x, dict)]
                for k, v in raw.items()
                if isinstance(v, list)
            }
    except Exception as e:
        try:
            current_app.logger.error(f"FCM tokens load failed: {e}")
        except Exception:
            pass
        try:
            if os.path.isfile(path):
                corrupt = f"{path}.corrupt.{int(time.time())}"
                os.replace(path, corrupt)
        except Exception:
            pass
    return {}


def _save_all(data: Dict[str, List[Dict[str, Any]]]) -> None:
    path = _tokens_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def register_token(
    phone: str,
    token: str,
    *,
    platform: str = "android",
    app_version: str = "",
) -> bool:
    phone_n = _normalize_phone(phone)
    token_s = (token or "").strip()
    if not phone_n or len(phone_n) != 11 or not token_s:
        return False

    data = _load_all()
    bucket = data.get(phone_n, [])
    now = int(time.time())
    updated = False
    for item in bucket:
        if item.get("token") == token_s:
            item["platform"] = platform or item.get("platform") or "android"
            item["app_version"] = app_version or item.get("app_version") or ""
            item["updated_at"] = now
            updated = True
            break
    if not updated:
        bucket.insert(0, {
            "token": token_s,
            "platform": platform or "android",
            "app_version": app_version or "",
            "updated_at": now,
        })
    bucket.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    data[phone_n] = bucket[:MAX_TOKENS_PER_USER]
    _save_all(data)
    return True


def unregister_token(token: str) -> bool:
    token_s = (token or "").strip()
    if not token_s:
        return False
    data = _load_all()
    changed = False
    for phone, items in list(data.items()):
        new_items = [x for x in items if x.get("token") != token_s]
        if len(new_items) != len(items):
            changed = True
            if new_items:
                data[phone] = new_items
            else:
                data.pop(phone, None)
    if changed:
        _save_all(data)
    return changed


def tokens_for_phones(phones: List[str]) -> List[str]:
    data = _load_all()
    out: List[str] = []
    seen = set()
    for raw in phones:
        phone_n = _normalize_phone(raw)
        for item in data.get(phone_n, []):
            tok = (item.get("token") or "").strip()
            if tok and tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def tokens_for_phone(phone: str) -> List[str]:
    return tokens_for_phones([phone])


def fcm_stats_for_phones(phones: List[str]) -> Dict[str, int]:
    """تعداد همکاران و دستگاه‌های دارای FCM token."""
    data = _load_all()
    users = 0
    for raw in phones:
        phone_n = _normalize_phone(raw)
        if phone_n and data.get(phone_n):
            users += 1
    devices = len(tokens_for_phones(phones))
    return {"users": users, "devices": devices}
