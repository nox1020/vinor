from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app

from app.memory.config import memory_max_bytes
from app.memory.interfaces import MemoryItem, MemoryStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_user_key(user_key: str) -> str:
    digits = re.sub(r"\D+", "", str(user_key or ""))
    if len(digits) >= 11:
        return digits[-11:]
    if len(digits) >= 8:
        return digits
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(user_key or ""))
    return safe[:64] if safe else ""


def default_memory_dir() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "instance")
        )
    path = os.path.join(base, "data", "ai_memory")
    os.makedirs(path, exist_ok=True)
    return path


def _payload_bytes(data: dict[str, Any]) -> int:
    # همان serialization که روی دیسک نوشته می‌شود (indent=2)
    return len(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def _item_sort_key(row: dict[str, Any]) -> str:
    return str(row.get("updated_at") or row.get("created_at") or "")


def _trim_items_to_quota(data: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """حذف قدیمی‌ترین آیتم‌ها تا حجم فایل زیر سقف کاربر بماند (in-place)."""
    items = [r for r in (data.get("items") or []) if isinstance(r, dict)]
    data["items"] = items
    data["max_bytes"] = int(max_bytes)
    while True:
        size = _payload_bytes(data)
        if size <= max_bytes:
            data["bytes_used"] = size
            return data
        items = data["items"]
        if not items:
            data["bytes_used"] = size
            return data
        if len(items) == 1:
            row = dict(items[0])
            val = str(row.get("value") or "")
            overhead = max(256, size - len(val.encode("utf-8")))
            allow = max(64, max_bytes - overhead)
            encoded = val.encode("utf-8")
            if len(encoded) > allow:
                row["value"] = encoded[:allow].decode("utf-8", errors="ignore")
                row["updated_at"] = _now_iso()
            data["items"] = [row]
            data["bytes_used"] = _payload_bytes(data)
            return data
        items = sorted(items, key=_item_sort_key)
        items.pop(0)
        data["items"] = items


class FileMemoryStore(MemoryStore):
    """فایل JSON اختصاصی هر کاربر — سقف حجم: memory_max_bytes() (پیش‌فرض ۱۰MB)."""

    def __init__(self, root_dir: str | None = None, *, max_bytes: int | None = None):
        self._root = root_dir or default_memory_dir()
        os.makedirs(self._root, exist_ok=True)
        self._lock = threading.Lock()
        self._max_bytes = int(max_bytes) if max_bytes is not None else memory_max_bytes()

    def max_bytes(self) -> int:
        return int(self._max_bytes)

    def usage_bytes(self, user_key: str) -> int:
        path = self._path(user_key)
        if not path or not os.path.isfile(path):
            return 0
        try:
            return int(os.path.getsize(path))
        except Exception:
            return 0

    def _path(self, user_key: str) -> str | None:
        key = _safe_user_key(user_key)
        if not key:
            return None
        return os.path.join(self._root, f"{key}.json")

    def _load(self, user_key: str) -> dict[str, Any]:
        path = self._path(user_key)
        blank = {
            "user_key": _safe_user_key(user_key),
            "items": [],
            "version": 1,
            "max_bytes": self._max_bytes,
            "bytes_used": 0,
        }
        if not path or not os.path.isfile(path):
            return blank
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return blank
            data.setdefault("items", [])
            data.setdefault("version", 1)
            data["max_bytes"] = self._max_bytes
            return data
        except Exception:
            return blank

    def _save(self, user_key: str, data: dict[str, Any]) -> None:
        path = self._path(user_key)
        if not path:
            return
        _trim_items_to_quota(data, self._max_bytes)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        try:
            data["bytes_used"] = int(os.path.getsize(path))
        except Exception:
            data["bytes_used"] = _payload_bytes(data)

    def list_items(self, user_key: str, *, memory_type: str | None = None) -> list[MemoryItem]:
        with self._lock:
            data = self._load(user_key)
        out: list[MemoryItem] = []
        for row in data.get("items") or []:
            if not isinstance(row, dict):
                continue
            if memory_type and str(row.get("memory_type") or "") != memory_type:
                continue
            out.append(_row_to_item(row))
        return out

    def upsert(self, item: MemoryItem) -> MemoryItem:
        with self._lock:
            data = self._load(item.user_key)
            items = [r for r in (data.get("items") or []) if isinstance(r, dict)]
            now = _now_iso()
            fp = _fingerprint(item.memory_type, item.key, item.value)
            for i, row in enumerate(items):
                same_key = (
                    str(row.get("memory_type") or "") == item.memory_type
                    and str(row.get("key") or "") == item.key
                )
                same_fp = str(row.get("fingerprint") or "") == fp
                if same_key or same_fp:
                    version = int(row.get("version") or 1) + 1
                    updated = {
                        **row,
                        "value": item.value,
                        "score": float(item.score),
                        "metadata": dict(item.metadata or {}),
                        "version": version,
                        "updated_at": now,
                        "fingerprint": fp,
                    }
                    items[i] = updated
                    data["items"] = items
                    data["version"] = int(data.get("version") or 1) + 1
                    self._save(item.user_key, data)
                    # ممکن است بعد از trim حذف شده باشد
                    for r in data.get("items") or []:
                        if isinstance(r, dict) and str(r.get("id") or "") == str(updated.get("id") or ""):
                            return _row_to_item(r)
                    return _row_to_item(updated)
            new_id = item.id or str(uuid.uuid4())
            row = {
                "id": new_id,
                "user_key": _safe_user_key(item.user_key),
                "memory_type": item.memory_type,
                "key": item.key,
                "value": item.value,
                "score": float(item.score),
                "metadata": dict(item.metadata or {}),
                "version": 1,
                "created_at": item.created_at or now,
                "updated_at": now,
                "fingerprint": fp,
            }
            items.append(row)
            data["items"] = items
            data["version"] = int(data.get("version") or 1) + 1
            self._save(item.user_key, data)
            for r in data.get("items") or []:
                if isinstance(r, dict) and str(r.get("id") or "") == new_id:
                    return _row_to_item(r)
            return _row_to_item(row)

    def delete(self, user_key: str, memory_id: str) -> bool:
        mid = str(memory_id or "").strip()
        if not mid:
            return False
        with self._lock:
            data = self._load(user_key)
            before = len(data.get("items") or [])
            data["items"] = [
                r
                for r in (data.get("items") or [])
                if isinstance(r, dict) and str(r.get("id") or "") != mid
            ]
            if len(data["items"]) == before:
                return False
            data["version"] = int(data.get("version") or 1) + 1
            self._save(user_key, data)
            return True

    def update(
        self,
        user_key: str,
        memory_id: str,
        *,
        value: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem | None:
        mid = str(memory_id or "").strip()
        if not mid:
            return None
        with self._lock:
            data = self._load(user_key)
            items = [r for r in (data.get("items") or []) if isinstance(r, dict)]
            for i, row in enumerate(items):
                if str(row.get("id") or "") != mid:
                    continue
                if value is not None:
                    row["value"] = str(value)
                if metadata is not None:
                    row["metadata"] = dict(metadata)
                row["version"] = int(row.get("version") or 1) + 1
                row["updated_at"] = _now_iso()
                row["fingerprint"] = _fingerprint(
                    str(row.get("memory_type") or ""),
                    str(row.get("key") or ""),
                    str(row.get("value") or ""),
                )
                items[i] = row
                data["items"] = items
                data["version"] = int(data.get("version") or 1) + 1
                self._save(user_key, data)
                for r in data.get("items") or []:
                    if isinstance(r, dict) and str(r.get("id") or "") == mid:
                        return _row_to_item(r)
                return _row_to_item(row)
        return None


class InMemoryMemoryStore(MemoryStore):
    """In-process store for tests/dev — همان سقف بایت اختصاصی هر کاربر."""

    def __init__(self, *, max_bytes: int | None = None):
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_bytes = int(max_bytes) if max_bytes is not None else memory_max_bytes()

    def max_bytes(self) -> int:
        return int(self._max_bytes)

    def usage_bytes(self, user_key: str) -> int:
        key = _safe_user_key(user_key)
        with self._lock:
            data = self._data.get(key)
            if not data:
                return 0
            return int(data.get("bytes_used") or _payload_bytes(data))

    def _blank(self, user_key: str) -> dict[str, Any]:
        return {
            "user_key": _safe_user_key(user_key),
            "items": [],
            "version": 1,
            "max_bytes": self._max_bytes,
            "bytes_used": 0,
        }

    def list_items(self, user_key: str, *, memory_type: str | None = None) -> list[MemoryItem]:
        key = _safe_user_key(user_key)
        with self._lock:
            rows = list((self._data.get(key) or {}).get("items") or [])
        out = []
        for row in rows:
            if memory_type and str(row.get("memory_type") or "") != memory_type:
                continue
            out.append(_row_to_item(row))
        return out

    def upsert(self, item: MemoryItem) -> MemoryItem:
        key = _safe_user_key(item.user_key)
        with self._lock:
            data = dict(self._data.get(key) or self._blank(item.user_key))
            rows = [dict(r) for r in (data.get("items") or []) if isinstance(r, dict)]
            fp = _fingerprint(item.memory_type, item.key, item.value)
            now = _now_iso()
            for i, row in enumerate(rows):
                if str(row.get("key") or "") == item.key and str(row.get("memory_type") or "") == item.memory_type:
                    row = {
                        **row,
                        "value": item.value,
                        "score": float(item.score),
                        "metadata": dict(item.metadata or {}),
                        "version": int(row.get("version") or 1) + 1,
                        "updated_at": now,
                        "fingerprint": fp,
                    }
                    rows[i] = row
                    data["items"] = rows
                    data["version"] = int(data.get("version") or 1) + 1
                    data = _trim_items_to_quota(data, self._max_bytes)
                    self._data[key] = data
                    for r in data.get("items") or []:
                        if str(r.get("id") or "") == str(row.get("id") or ""):
                            return _row_to_item(r)
                    return _row_to_item(row)
            row = {
                "id": item.id or str(uuid.uuid4()),
                "user_key": key,
                "memory_type": item.memory_type,
                "key": item.key,
                "value": item.value,
                "score": float(item.score),
                "metadata": dict(item.metadata or {}),
                "version": 1,
                "created_at": now,
                "updated_at": now,
                "fingerprint": fp,
            }
            rows.append(row)
            data["items"] = rows
            data["version"] = int(data.get("version") or 1) + 1
            data = _trim_items_to_quota(data, self._max_bytes)
            self._data[key] = data
            for r in data.get("items") or []:
                if str(r.get("id") or "") == str(row.get("id") or ""):
                    return _row_to_item(r)
            return _row_to_item(row)

    def delete(self, user_key: str, memory_id: str) -> bool:
        key = _safe_user_key(user_key)
        mid = str(memory_id or "").strip()
        with self._lock:
            data = dict(self._data.get(key) or self._blank(user_key))
            rows = list(data.get("items") or [])
            nxt = [r for r in rows if str(r.get("id") or "") != mid]
            if len(nxt) == len(rows):
                return False
            data["items"] = nxt
            data["version"] = int(data.get("version") or 1) + 1
            self._data[key] = _trim_items_to_quota(data, self._max_bytes)
            return True

    def update(
        self,
        user_key: str,
        memory_id: str,
        *,
        value: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem | None:
        key = _safe_user_key(user_key)
        mid = str(memory_id or "").strip()
        with self._lock:
            data = dict(self._data.get(key) or self._blank(user_key))
            rows = [dict(r) for r in (data.get("items") or []) if isinstance(r, dict)]
            for i, row in enumerate(rows):
                if str(row.get("id") or "") != mid:
                    continue
                if value is not None:
                    row["value"] = str(value)
                if metadata is not None:
                    row["metadata"] = dict(metadata)
                row["version"] = int(row.get("version") or 1) + 1
                row["updated_at"] = _now_iso()
                rows[i] = row
                data["items"] = rows
                data["version"] = int(data.get("version") or 1) + 1
                data = _trim_items_to_quota(data, self._max_bytes)
                self._data[key] = data
                for r in data.get("items") or []:
                    if str(r.get("id") or "") == mid:
                        return _row_to_item(r)
                return _row_to_item(row)
        return None


def _fingerprint(memory_type: str, key: str, value: str) -> str:
    raw = f"{memory_type}|{key}|{value}".strip().lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _row_to_item(row: dict[str, Any]) -> MemoryItem:
    return MemoryItem(
        id=str(row.get("id") or ""),
        user_key=str(row.get("user_key") or ""),
        memory_type=str(row.get("memory_type") or ""),
        key=str(row.get("key") or ""),
        value=str(row.get("value") or ""),
        score=float(row.get("score") or 1.0),
        metadata=dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {},
        version=int(row.get("version") or 1),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )
