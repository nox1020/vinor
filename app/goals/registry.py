from __future__ import annotations

import json
import os
import threading
from typing import Any

from app.goals.interfaces import GoalRegistry

_LOCK = threading.Lock()


def _dir() -> str:
    try:
        from flask import current_app

        root = current_app.instance_path
    except Exception:
        root = os.path.join(os.getcwd(), "instance")
    path = os.path.join(root, "data", "ai_goals")
    os.makedirs(path, exist_ok=True)
    return path


def _path(user_key: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (user_key or "anon"))[:64]
    return os.path.join(_dir(), f"{safe}.json")


class SessionGoalRegistry(GoalRegistry):
    """Session-scoped goals file — not a new Memory Store."""

    def load(self, user_key: str) -> list[dict[str, Any]]:
        path = _path(user_key)
        if not os.path.isfile(path):
            return []
        try:
            with _LOCK:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if isinstance(data, dict):
                return list(data.get("goals") or [])
            if isinstance(data, list):
                return list(data)
        except Exception:
            return []
        return []

    def save(self, user_key: str, goals: list[dict[str, Any]]) -> None:
        path = _path(user_key)
        try:
            with _LOCK:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"goals": list(goals)[:20]}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
