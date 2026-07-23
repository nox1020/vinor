# -*- coding: utf-8 -*-
"""Shared business/system memory — instance/data/ai_system_memory.json."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def system_memory_path() -> str:
    try:
        from app.utils.storage import data_dir

        root = data_dir()
    except Exception:
        root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "instance", "data")
        )
        os.makedirs(root, exist_ok=True)
    return os.path.join(root, "ai_system_memory.json")


def _blank() -> dict[str, Any]:
    return {"items": [], "version": 1}


def _load() -> dict[str, Any]:
    path = system_memory_path()
    if not path or not os.path.isfile(path):
        return _blank()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _blank()
        items = data.get("items")
        if not isinstance(items, list):
            data["items"] = []
        data.setdefault("version", 1)
        return data
    except Exception:
        return _blank()


def _save(data: dict[str, Any]) -> None:
    path = system_memory_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_items() -> List[dict[str, Any]]:
    """Return system memory rows (fail-open)."""
    try:
        with _lock:
            data = _load()
        out: List[dict[str, Any]] = []
        for row in data.get("items") or []:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "key": str(row.get("key") or ""),
                    "value": str(row.get("value") or ""),
                    "created_at": str(row.get("created_at") or ""),
                    "updated_at": str(row.get("updated_at") or ""),
                }
            )
        return out
    except Exception:
        return []


def add(key: str, value: str) -> Optional[dict[str, Any]]:
    """Add a business fact. Returns the new row or None on failure."""
    k = (key or "").strip()
    v = (value or "").strip()
    if not k or not v:
        return None
    try:
        with _lock:
            data = _load()
            items = [r for r in (data.get("items") or []) if isinstance(r, dict)]
            now = _now_iso()
            # Upsert by key (case-insensitive)
            for i, row in enumerate(items):
                if str(row.get("key") or "").strip().lower() == k.lower():
                    updated = {
                        **row,
                        "key": k,
                        "value": v,
                        "updated_at": now,
                    }
                    items[i] = updated
                    data["items"] = items
                    data["version"] = int(data.get("version") or 1) + 1
                    _save(data)
                    return {
                        "id": str(updated.get("id") or ""),
                        "key": k,
                        "value": v,
                        "created_at": str(updated.get("created_at") or now),
                        "updated_at": now,
                    }
            new_id = str(uuid.uuid4())
            row = {
                "id": new_id,
                "key": k,
                "value": v,
                "created_at": now,
                "updated_at": now,
            }
            items.append(row)
            data["items"] = items
            data["version"] = int(data.get("version") or 1) + 1
            _save(data)
            return dict(row)
    except Exception:
        return None


def delete(item_id: str) -> bool:
    mid = str(item_id or "").strip()
    if not mid:
        return False
    try:
        with _lock:
            data = _load()
            before = len(data.get("items") or [])
            data["items"] = [
                r
                for r in (data.get("items") or [])
                if isinstance(r, dict) and str(r.get("id") or "") != mid
            ]
            if len(data["items"]) == before:
                return False
            data["version"] = int(data.get("version") or 1) + 1
            _save(data)
            return True
    except Exception:
        return False


def system_memory_prompt_text(*, max_chars: int = 1200) -> str:
    """Compact prompt block for chat — fail-open, hard char budget.

    Long facts are truncated to fit; a fact that does not fit whole is never
    skipped entirely when there is still room (avoids empty blocks).
    """
    try:
        try:
            budget = max(80, int(max_chars))
        except Exception:
            budget = 1200
        items = list_items()
        if not items:
            return ""
        header = "=== دانش کسب‌وکار ===\n"
        lines: list[str] = []
        used = len(header)
        for it in items:
            key = (it.get("key") or "").strip()
            val = (it.get("value") or "").strip()
            if not val:
                continue
            # Room for this line (+ joining newline when not first).
            room = budget - used - (1 if lines else 0)
            if room < 24:
                break
            prefix = f"- {key}: " if key else "- "
            if len(prefix) >= room:
                break
            avail = room - len(prefix)
            if len(val) > avail:
                val = val[: max(0, avail - 1)].rstrip() + "…"
            if not val:
                break
            line = prefix + val
            if lines:
                used += 1
            lines.append(line)
            used += len(line)
        if not lines:
            return ""
        text = header + "\n".join(lines)
        if len(text) > budget:
            text = text[: max(0, budget - 1)].rstrip() + "…"
        return text
    except Exception:
        return ""
