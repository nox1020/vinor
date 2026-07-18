# -*- coding: utf-8 -*-
"""Fail-open readers for AI Mission Control data stores."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, List, Optional


def _mask_phone(key: str) -> str:
    raw = re.sub(r"\D+", "", str(key or ""))
    if len(raw) >= 7:
        return raw[:4] + "***" + raw[-3:]
    if not raw:
        return (key or "")[:8] + "…" if len(str(key or "")) > 8 else (key or "—")
    return raw


def _tail_jsonl(path: str, *, limit: int = 200) -> List[dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    out: List[dict[str, Any]] = []
    for line in reversed(lines[-max(limit * 2, limit) :]):
        line = (line or "").strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
        if len(out) >= limit:
            break
    return out


def list_conversation_index(*, limit: int = 100, audience: str = "", q: str = "") -> List[dict[str, Any]]:
    """Scan ai_chats/{audience}/*.json → thread summaries."""
    try:
        from app.ai.paths import ai_data_file

        root = ai_data_file("ai_chats")
    except Exception:
        return []
    if not os.path.isdir(root):
        return []
    audiences = [audience] if audience in ("public", "partner") else ["public", "partner"]
    q_norm = (q or "").strip().lower()
    rows: List[dict[str, Any]] = []
    for aud in audiences:
        sub = os.path.join(root, aud)
        if not os.path.isdir(sub):
            continue
        try:
            files = os.listdir(sub)
        except Exception:
            continue
        for name in files:
            if not name.endswith(".json"):
                continue
            path = os.path.join(sub, name)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            user_key = str(data.get("user_key") or name.replace(".json", ""))
            if q_norm and q_norm not in user_key.lower() and q_norm not in name.lower():
                continue
            for th in data.get("threads") or []:
                if not isinstance(th, dict):
                    continue
                msgs = th.get("messages") if isinstance(th.get("messages"), list) else []
                last_role = ""
                last_preview = ""
                if msgs:
                    last = msgs[-1] if isinstance(msgs[-1], dict) else {}
                    last_role = str(last.get("role") or "")
                    last_preview = str(last.get("content") or "")[:80]
                rows.append(
                    {
                        "audience": aud,
                        "user_key": user_key,
                        "user_masked": _mask_phone(user_key),
                        "thread_id": str(th.get("id") or ""),
                        "title": str(th.get("title") or "گفتگو"),
                        "msg_count": len(msgs),
                        "updated_at": str(th.get("updated_at") or th.get("created_at") or ""),
                        "last_role": last_role,
                        "last_preview": last_preview,
                    }
                )
    rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return rows[: max(1, int(limit or 100))]


def get_conversation(
    *,
    audience: str,
    user_key: str,
    thread_id: str = "",
) -> Optional[dict[str, Any]]:
    try:
        from app.ai.chat_store import load_user_record

        record = load_user_record(user_key, audience)
    except Exception:
        return None
    threads = list(record.get("threads") or [])
    th = None
    tid = (thread_id or "").strip()
    if tid:
        for t in threads:
            if isinstance(t, dict) and str(t.get("id") or "") == tid:
                th = t
                break
    if th is None and threads:
        th = threads[0]
    if th is None:
        return {
            "audience": audience,
            "user_key": user_key,
            "user_masked": _mask_phone(user_key),
            "thread": None,
            "messages": [],
        }
    msgs = []
    for m in th.get("messages") or []:
        if not isinstance(m, dict):
            continue
        content = str(m.get("content") or "")
        msgs.append(
            {
                "role": str(m.get("role") or ""),
                "content": content,
                "content_preview": content[:500],
                "ts": str(m.get("ts") or m.get("created_at") or ""),
            }
        )
    return {
        "audience": audience,
        "user_key": user_key,
        "user_masked": _mask_phone(user_key),
        "thread": {
            "id": str(th.get("id") or ""),
            "title": str(th.get("title") or ""),
            "updated_at": str(th.get("updated_at") or ""),
        },
        "messages": msgs,
        "reasoning_summary": {
            "note": "Structured summary only — no chain-of-thought.",
            "intent": "",
            "agents": [],
            "tools": [],
            "gates": [],
            "hint": "Per-turn obs (g.*) is request-scoped; use evaluation/token logs for historical signals.",
        },
    }


def list_pending_confirms(*, limit: int = 100) -> List[dict[str, Any]]:
    try:
        from datetime import timedelta

        from app.ai.agent_tools import _PENDING_TTL_MIN, _read_pending_store

        store = _read_pending_store()
        ttl = int(_PENDING_TTL_MIN or 30)
    except Exception:
        return []
    now = datetime.now(timezone.utc)
    rows = []
    for token, row in (store or {}).items():
        if not isinstance(row, dict):
            continue
        created = str(row.get("created_at") or "")
        status = "pending"
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if now - created_dt > timedelta(minutes=ttl):
                status = "expired"
        except Exception:
            pass
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        rows.append(
            {
                "token": str(token)[:16] + "…",
                "token_full": str(token),
                "user_key": str(row.get("user_key") or ""),
                "user_masked": _mask_phone(str(row.get("user_key") or "")),
                "action_type": str(row.get("action_type") or ""),
                "created_at": created,
                "status": status,
                "land_code": str(payload.get("land_code") or ""),
                "summary": str(row.get("action_type") or "")
                + (f" · {payload.get('land_code')}" if payload.get("land_code") else ""),
            }
        )
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[: max(1, int(limit or 100))]


def expire_pending_token(token: str) -> bool:
    try:
        from app.ai.agent_tools import _read_pending_store, _write_pending_store

        store = _read_pending_store()
        tok = (token or "").strip()
        if tok not in store:
            return False
        del store[tok]
        _write_pending_store(store)
        return True
    except Exception:
        return False


def list_workflow_sessions(*, limit: int = 100) -> List[dict[str, Any]]:
    try:
        from app.conversation.session import _store_dir

        root = _store_dir()
    except Exception:
        return []
    if not os.path.isdir(root):
        return []
    rows = []
    try:
        names = os.listdir(root)
    except Exception:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        rows.append(
            {
                "session_id": str(d.get("session_id") or ""),
                "user_key": str(d.get("user_key") or ""),
                "user_masked": _mask_phone(str(d.get("user_key") or "")),
                "workflow_id": str(d.get("workflow_id") or ""),
                "intent": str(d.get("intent") or ""),
                "state": str(d.get("state") or ""),
                "current_step": str(d.get("current_step") or ""),
                "missing": list(d.get("missing") or []),
                "updated_at": d.get("updated_at") or 0,
            }
        )
    rows.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
    return rows[: max(1, int(limit or 100))]


def list_evaluation_rows(*, limit: int = 100) -> List[dict[str, Any]]:
    try:
        from app.evaluation.storage import evaluation_log_path

        path = evaluation_log_path()
    except Exception:
        try:
            from app.utils.storage import data_dir

            path = os.path.join(data_dir(), "ai_evaluation.jsonl")
        except Exception:
            return []
    return _tail_jsonl(path, limit=limit)


def list_token_rows(*, limit: int = 100) -> List[dict[str, Any]]:
    try:
        from app.ai.token_analytics import _analytics_path

        path = _analytics_path()
    except Exception:
        try:
            from app.utils.storage import data_dir

            path = os.path.join(data_dir(), "ai_token_analytics.jsonl")
        except Exception:
            return []
    return _tail_jsonl(path, limit=limit)


def list_escalations(*, limit: int = 50) -> List[dict[str, Any]]:
    try:
        from app.ai.paths import ensure_escalations_file

        path = ensure_escalations_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    rows = [r for r in data if isinstance(r, dict)]
    rows = list(reversed(rows[-limit:]))
    return rows[:limit]


def list_memory_users(*, limit: int = 100) -> List[dict[str, Any]]:
    try:
        from app.memory.store import default_memory_dir

        root = default_memory_dir()
    except Exception:
        return []
    if not os.path.isdir(root):
        return []
    rows = []
    try:
        names = os.listdir(root)
    except Exception:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        items = d.get("items") if isinstance(d, dict) else []
        if not isinstance(items, list):
            items = []
        uk = str((d or {}).get("user_key") or name.replace(".json", ""))
        rows.append(
            {
                "user_key": uk,
                "user_masked": _mask_phone(uk),
                "item_count": len(items),
                "file": name,
            }
        )
    rows.sort(key=lambda r: int(r.get("item_count") or 0), reverse=True)
    return rows[: max(1, int(limit or 100))]


def get_memory_detail(user_key: str) -> dict[str, Any]:
    try:
        from app.memory.store import FileMemoryStore

        store = FileMemoryStore()
        data = store._load(user_key)  # noqa: SLF001 — admin read
    except Exception:
        return {"user_key": user_key, "user_masked": _mask_phone(user_key), "items": []}
    items = []
    for it in data.get("items") or []:
        if isinstance(it, dict):
            items.append(
                {
                    "id": str(it.get("id") or ""),
                    "type": str(it.get("type") or it.get("kind") or ""),
                    "text": str(it.get("text") or it.get("content") or "")[:300],
                    "created_at": str(it.get("created_at") or ""),
                }
            )
        elif hasattr(it, "to_dict"):
            d = it.to_dict()
            items.append(
                {
                    "id": str(d.get("id") or ""),
                    "type": str(d.get("type") or ""),
                    "text": str(d.get("text") or "")[:300],
                    "created_at": str(d.get("created_at") or ""),
                }
            )
    return {
        "user_key": user_key,
        "user_masked": _mask_phone(user_key),
        "items": items,
    }


def extract_errors_from_logs(*, limit: int = 50) -> List[dict[str, Any]]:
    """Heuristic errors from evaluation + token rows."""
    errors = []
    for row in list_evaluation_rows(limit=limit * 2):
        ok = row.get("ok")
        err = row.get("error") or row.get("failed") or row.get("status")
        if ok is False or err in ("error", "failed") or row.get("quality_score") == 0:
            errors.append(
                {
                    "source": "evaluation",
                    "ts": str(row.get("ts") or row.get("created_at") or ""),
                    "type": str(row.get("error_type") or "eval"),
                    "message": str(row.get("error") or row.get("summary") or "evaluation issue")[:200],
                    "request_id": str(row.get("request_id") or ""),
                    "audience": str(row.get("audience") or ""),
                }
            )
        if len(errors) >= limit:
            break
    for row in list_token_rows(limit=limit):
        if row.get("error") or row.get("ok") is False:
            errors.append(
                {
                    "source": "tokens",
                    "ts": str(row.get("ts") or row.get("created_at") or ""),
                    "type": "token",
                    "message": str(row.get("error") or "token analytics error")[:200],
                    "request_id": str(row.get("request_id") or ""),
                    "audience": str(row.get("audience") or ""),
                }
            )
        if len(errors) >= limit:
            break
    return errors[:limit]
