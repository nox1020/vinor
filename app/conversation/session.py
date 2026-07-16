from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any

from app.conversation.interfaces import ConversationSession, SessionStore

_LOCK = threading.Lock()


def _store_dir() -> str:
    try:
        from flask import current_app

        root = current_app.instance_path
    except Exception:
        root = os.path.join(os.getcwd(), "instance")
    path = os.path.join(root, "data", "ai_conversation")
    os.makedirs(path, exist_ok=True)
    return path


def _path_for(user_key: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (user_key or "anon"))[:64]
    return os.path.join(_store_dir(), f"{safe}.json")


def _to_dict(s: ConversationSession) -> dict[str, Any]:
    return {
        "session_id": s.session_id,
        "user_key": s.user_key,
        "role": s.role,
        "intent": s.intent,
        "workflow_id": s.workflow_id,
        "workflow_name": getattr(s, "workflow_name", "") or "",
        "state": s.state,
        "current_step": s.current_step,
        "collected": dict(s.collected or {}),
        "missing": list(s.missing or []),
        "completed_steps": list(getattr(s, "completed_steps", None) or []),
        "validation_errors": list(getattr(s, "validation_errors", None) or []),
        "object_type": s.object_type,
        "started_at": s.started_at,
        "updated_at": s.updated_at,
        "metadata": dict(s.metadata or {}),
    }


def _from_dict(d: dict[str, Any]) -> ConversationSession:
    return ConversationSession(
        session_id=str(d.get("session_id") or ""),
        user_key=str(d.get("user_key") or ""),
        role=str(d.get("role") or ""),
        intent=str(d.get("intent") or ""),
        workflow_id=str(d.get("workflow_id") or ""),
        workflow_name=str(d.get("workflow_name") or ""),
        state=str(d.get("state") or ""),
        current_step=str(d.get("current_step") or ""),
        collected=dict(d.get("collected") or {}),
        missing=list(d.get("missing") or []),
        completed_steps=list(d.get("completed_steps") or []),
        validation_errors=list(d.get("validation_errors") or []),
        object_type=str(d.get("object_type") or ""),
        started_at=float(d.get("started_at") or 0),
        updated_at=float(d.get("updated_at") or 0),
        metadata=dict(d.get("metadata") or {}),
    )


class FileSessionStore(SessionStore):
    """Persist conversation session outside Prompt."""

    def load(self, user_key: str) -> ConversationSession | None:
        path = _path_for(user_key)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return None
            return _from_dict(raw)
        except Exception:
            return None

    def save(self, session: ConversationSession) -> None:
        session.updated_at = time.time()
        path = _path_for(session.user_key)
        with _LOCK:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_to_dict(session), f, ensure_ascii=False, indent=2)

    def clear(self, user_key: str) -> None:
        path = _path_for(user_key)
        with _LOCK:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass


def new_session(*, user_key: str, role: str) -> ConversationSession:
    now = time.time()
    return ConversationSession(
        session_id=uuid.uuid4().hex[:16],
        user_key=user_key,
        role=role,
        started_at=now,
        updated_at=now,
    )
