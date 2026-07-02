# -*- coding: utf-8 -*-
"""ذخیره FCM tokenهای دستگاه همکاران."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from flask import current_app

MAX_TOKENS_PER_USER = 5
STALE_TOKEN_DAYS = 90

try:
    import fcntl as _fcntl  # type: ignore
except Exception:
    _fcntl = None


def _tokens_path() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "instance")
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "fcm_tokens.json")


def _lock_path() -> str:
    return f"{_tokens_path()}.lock"


@contextmanager
def _token_store_lock() -> Iterator[None]:
    """قفل فایل برای جلوگیری از race بین workerهای Passenger."""
    lock_file = _lock_path()
    fh = open(lock_file, "a+", encoding="utf-8")
    try:
        if _fcntl is not None:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)
        yield
    finally:
        try:
            if _fcntl is not None:
                _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
        except Exception:
            pass
        fh.close()


def _normalize_phone(phone: str) -> str:
    from app.services.notifications import _normalize_user_id
    return _normalize_user_id(phone or "")


def _load_all_unlocked() -> Dict[str, List[Dict[str, Any]]]:
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


def _save_all_unlocked(data: Dict[str, List[Dict[str, Any]]]) -> None:
    path = _tokens_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _prune_stale_unlocked(data: Dict[str, List[Dict[str, Any]]], *, max_age_days: int = STALE_TOKEN_DAYS) -> int:
    cutoff = int(time.time()) - max(1, max_age_days) * 86400
    removed = 0
    for phone, items in list(data.items()):
        kept = [x for x in items if int(x.get("updated_at") or 0) >= cutoff]
        removed += len(items) - len(kept)
        if kept:
            data[phone] = kept[:MAX_TOKENS_PER_USER]
        else:
            data.pop(phone, None)
    return removed


def _detach_token_from_other_users_unlocked(data: Dict[str, List[Dict[str, Any]]], phone_n: str, token_s: str) -> int:
    """هر token فقط به یک کاربر تعلق دارد — از بقیه حذف می‌شود."""
    moved = 0
    for other_phone, items in list(data.items()):
        if other_phone == phone_n:
            continue
        filtered = [x for x in items if (x.get("token") or "").strip() != token_s]
        if len(filtered) != len(items):
            moved += len(items) - len(filtered)
            if filtered:
                data[other_phone] = filtered
            else:
                data.pop(other_phone, None)
    return moved


def all_registered() -> Dict[str, List[Dict[str, Any]]]:
    """همه tokenهای ثبت‌شده — برای admin/debug."""
    return _load_all_unlocked()


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

    with _token_store_lock():
        data = _load_all_unlocked()
        _prune_stale_unlocked(data)
        _detach_token_from_other_users_unlocked(data, phone_n, token_s)

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
        _save_all_unlocked(data)
    return True


def unregister_token(token: str) -> bool:
    token_s = (token or "").strip()
    if not token_s:
        return False
    with _token_store_lock():
        data = _load_all_unlocked()
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
            _save_all_unlocked(data)
    return changed


def unregister_token_for_phone(phone: str, token: str) -> bool:
    phone_n = _normalize_phone(phone)
    token_s = (token or "").strip()
    if not phone_n or not token_s:
        return False
    with _token_store_lock():
        data = _load_all_unlocked()
        items = data.get(phone_n, [])
        new_items = [x for x in items if x.get("token") != token_s]
        if len(new_items) == len(items):
            return False
        if new_items:
            data[phone_n] = new_items
        else:
            data.pop(phone_n, None)
        _save_all_unlocked(data)
    return True


def unregister_all_for_phone(phone: str) -> int:
    phone_n = _normalize_phone(phone)
    if not phone_n:
        return 0
    with _token_store_lock():
        data = _load_all_unlocked()
        count = len(data.get(phone_n, []))
        if count:
            data.pop(phone_n, None)
            _save_all_unlocked(data)
    return count


def token_owned_by_phone(phone: str, token: str) -> bool:
    phone_n = _normalize_phone(phone)
    token_s = (token or "").strip()
    if not phone_n or not token_s:
        return False
    data = _load_all_unlocked()
    return any((x.get("token") or "").strip() == token_s for x in data.get(phone_n, []))


def tokens_for_phones(phones: List[str]) -> List[str]:
    data = _load_all_unlocked()
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


def list_tokens_for_phone(phone: str) -> List[Dict[str, Any]]:
    phone_n = _normalize_phone(phone)
    if not phone_n:
        return []
    data = _load_all_unlocked()
    return list(data.get(phone_n, []))


def fcm_stats_for_phones(phones: List[str]) -> Dict[str, int]:
    """تعداد همکاران و دستگاه‌های دارای FCM token."""
    data = _load_all_unlocked()
    users = 0
    for raw in phones:
        phone_n = _normalize_phone(raw)
        if phone_n and data.get(phone_n):
            users += 1
    devices = len(tokens_for_phones(phones))
    return {"users": users, "devices": devices}
