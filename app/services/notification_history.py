# -*- coding: utf-8 -*-
"""سابقه ارسال اعلان‌های ادمین به همکاران (broadcast-level)."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import current_app

MAX_BROADCASTS = 500


def _history_file_path() -> str:
    try:
        instance_path = current_app.instance_path
    except Exception:
        instance_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "instance"
        )
    data_dir = os.path.join(instance_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "notification_broadcasts.json")


def load_broadcast_history() -> List[Dict[str, Any]]:
    path = _history_file_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    except Exception as e:
        try:
            current_app.logger.error(f"Error loading notification broadcast history: {e}")
        except Exception:
            pass
    return []


def _save_broadcast_history(items: List[Dict[str, Any]]) -> bool:
    path = _history_file_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error saving notification broadcast history: {e}", exc_info=True)
        except Exception:
            pass
        return False


def append_broadcast(
    *,
    title: str,
    body: str,
    ntype: str = "info",
    recipient_count: int = 0,
    success_count: int = 0,
    failed_count: int = 0,
    push_sent: int = 0,
    push_failed: int = 0,
    source: str = "admin_colleagues",
    broadcast_id: Optional[str] = None,
    admin_user: Optional[str] = None,
) -> Dict[str, Any]:
    record = {
        "id": broadcast_id or str(uuid.uuid4()),
        "title": str(title or "").strip(),
        "body": str(body or "").strip(),
        "type": str(ntype or "info").strip() or "info",
        "created_at": int(time.time()),
        "recipient_count": int(recipient_count or 0),
        "success_count": int(success_count or 0),
        "failed_count": int(failed_count or 0),
        "push_sent": int(push_sent or 0),
        "push_failed": int(push_failed or 0),
        "source": str(source or "admin_colleagues"),
        "admin_user": (admin_user or "").strip() or None,
    }
    history = load_broadcast_history()
    history.insert(0, record)
    if len(history) > MAX_BROADCASTS:
        history = history[:MAX_BROADCASTS]
    _save_broadcast_history(history)
    return record


def list_broadcasts(limit: int = 40, offset: int = 0) -> List[Dict[str, Any]]:
    history = load_broadcast_history()
    history.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    start = max(0, int(offset or 0))
    end = start + max(1, int(limit or 40))
    return history[start:end]


def broadcast_stats() -> Dict[str, int]:
    history = load_broadcast_history()
    total = len(history)
    sent_ok = sum(int(h.get("success_count") or 0) for h in history)
    sent_fail = sum(int(h.get("failed_count") or 0) for h in history)
    return {
        "total_broadcasts": total,
        "total_delivered": sent_ok,
        "total_failed": sent_fail,
    }
