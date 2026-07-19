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


def _safe_key(raw: str, *, max_len: int = 64) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (raw or "anon"))[:max_len]


def _path_for(user_key: str, thread_id: str | None = None) -> str:
    """Legacy: `{user}.json`. Thread-scoped: `{user}__t__{thread}.json`."""
    safe_user = _safe_key(user_key)
    tid = (thread_id or "").strip()
    if tid:
        return os.path.join(_store_dir(), f"{safe_user}__t__{_safe_key(tid, max_len=48)}.json")
    return os.path.join(_store_dir(), f"{safe_user}.json")


def _thread_id_of(session: ConversationSession) -> str | None:
    meta = session.metadata if isinstance(session.metadata, dict) else {}
    tid = str(meta.get("thread_id") or "").strip()
    return tid or None


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
    """Persist conversation session outside Prompt — scoped by user_key + thread_id."""

    def load(self, user_key: str, thread_id: str | None = None) -> ConversationSession | None:
        path = _path_for(user_key, thread_id)
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
        path = _path_for(session.user_key, _thread_id_of(session))
        with _LOCK:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_to_dict(session), f, ensure_ascii=False, indent=2)

    def clear(self, user_key: str, thread_id: str | None = None) -> None:
        tid = (thread_id or "").strip() or None
        with _LOCK:
            if tid:
                path = _path_for(user_key, tid)
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except Exception:
                    pass
                return
            # No thread: clear legacy file + all thread-scoped sessions for this user.
            legacy = _path_for(user_key, None)
            try:
                if os.path.isfile(legacy):
                    os.remove(legacy)
            except Exception:
                pass
            prefix = f"{_safe_key(user_key)}__t__"
            try:
                for name in os.listdir(_store_dir()):
                    if name.startswith(prefix) and name.endswith(".json"):
                        try:
                            os.remove(os.path.join(_store_dir(), name))
                        except Exception:
                            pass
            except Exception:
                pass


def new_session(*, user_key: str, role: str, thread_id: str | None = None) -> ConversationSession:
    now = time.time()
    meta: dict[str, Any] = {}
    tid = (thread_id or "").strip()
    if tid:
        meta["thread_id"] = tid
    return ConversationSession(
        session_id=uuid.uuid4().hex[:16],
        user_key=user_key,
        role=role,
        started_at=now,
        updated_at=now,
        metadata=meta,
    )
