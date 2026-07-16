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


class FileMemoryStore(MemoryStore):
    """JSON file store per user — swappable later with Redis/Postgres."""

    def __init__(self, root_dir: str | None = None):
        self._root = root_dir or default_memory_dir()
        os.makedirs(self._root, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, user_key: str) -> str | None:
        key = _safe_user_key(user_key)
        if not key:
            return None
        return os.path.join(self._root, f"{key}.json")

    def _load(self, user_key: str) -> dict[str, Any]:
        path = self._path(user_key)
        if not path or not os.path.isfile(path):
            return {"user_key": _safe_user_key(user_key), "items": [], "version": 1}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"user_key": _safe_user_key(user_key), "items": [], "version": 1}
            data.setdefault("items", [])
            data.setdefault("version", 1)
            return data
        except Exception:
            return {"user_key": _safe_user_key(user_key), "items": [], "version": 1}

    def _save(self, user_key: str, data: dict[str, Any]) -> None:
        path = self._path(user_key)
        if not path:
            return
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

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
            # Dedup by type+key fingerprint
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
                    data["items"] = items[-400:]
                    data["version"] = int(data.get("version") or 1) + 1
                    self._save(item.user_key, data)
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
            data["items"] = items[-400:]
            data["version"] = int(data.get("version") or 1) + 1
            self._save(item.user_key, data)
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
                return _row_to_item(row)
        return None


class InMemoryMemoryStore(MemoryStore):
    """In-process store for tests/dev."""

    def __init__(self):
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def list_items(self, user_key: str, *, memory_type: str | None = None) -> list[MemoryItem]:
        key = _safe_user_key(user_key)
        with self._lock:
            rows = list(self._data.get(key) or [])
        out = []
        for row in rows:
            if memory_type and str(row.get("memory_type") or "") != memory_type:
                continue
            out.append(_row_to_item(row))
        return out

    def upsert(self, item: MemoryItem) -> MemoryItem:
        key = _safe_user_key(item.user_key)
        with self._lock:
            rows = list(self._data.get(key) or [])
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
                    self._data[key] = rows
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
            self._data[key] = rows[-400:]
            return _row_to_item(row)

    def delete(self, user_key: str, memory_id: str) -> bool:
        key = _safe_user_key(user_key)
        mid = str(memory_id or "").strip()
        with self._lock:
            rows = list(self._data.get(key) or [])
            nxt = [r for r in rows if str(r.get("id") or "") != mid]
            if len(nxt) == len(rows):
                return False
            self._data[key] = nxt
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
            rows = list(self._data.get(key) or [])
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
                self._data[key] = rows
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
