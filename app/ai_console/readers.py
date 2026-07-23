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


def _bytes_human(n: int) -> str:
    try:
        n = int(n or 0)
    except Exception:
        n = 0
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def count_memory_users() -> int:
    """Count per-user ai_memory JSON files (fail-open)."""
    try:
        from app.memory.store import default_memory_dir

        root = default_memory_dir()
    except Exception:
        return 0
    if not os.path.isdir(root):
        return 0
    try:
        names = os.listdir(root)
    except Exception:
        return 0
    n = 0
    for name in names:
        if not name.endswith(".json"):
            continue
        if name in ("partner_live",):
            continue
        path = os.path.join(root, name)
        if os.path.isfile(path):
            n += 1
    return n


def list_memory_users(*, limit: int = 100, q: str = "") -> List[dict[str, Any]]:
    try:
        from app.memory.store import default_memory_dir

        root = default_memory_dir()
    except Exception:
        return []
    if not os.path.isdir(root):
        return []
    q_norm = (q or "").strip().lower()
    q_digits = re.sub(r"\D+", "", q or "")
    rows = []
    try:
        names = os.listdir(root)
    except Exception:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        # Skip nested partner_live directory entries if listed as files
        if name in ("partner_live",):
            continue
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        items = d.get("items") if isinstance(d, dict) else []
        if not isinstance(items, list):
            items = []
        uk = str((d or {}).get("user_key") or name.replace(".json", ""))
        if q_norm or q_digits:
            uk_l = uk.lower()
            masked = _mask_phone(uk).lower()
            uk_digits = re.sub(r"\D+", "", uk)
            hit = (
                (q_norm and (q_norm in uk_l or q_norm in masked or q_norm in name.lower()))
                or (q_digits and q_digits in uk_digits)
            )
            if not hit:
                continue
        try:
            bytes_used = int(os.path.getsize(path))
        except Exception:
            bytes_used = int((d or {}).get("bytes_used") or 0) if isinstance(d, dict) else 0
        rows.append(
            {
                "user_key": uk,
                "user_masked": _mask_phone(uk),
                "item_count": len(items),
                "bytes_used": bytes_used,
                "bytes_label": _bytes_human(bytes_used),
                "file": name,
            }
        )
    rows.sort(key=lambda r: int(r.get("item_count") or 0), reverse=True)
    return rows[: max(1, int(limit or 100))]


def get_memory_detail(user_key: str) -> dict[str, Any]:
    blank = {
        "user_key": user_key,
        "user_masked": _mask_phone(user_key),
        "memory_items": [],
        "bytes_used": 0,
        "bytes_label": "0 B",
        "max_bytes": 0,
        "max_bytes_label": "0 B",
        "partner_live": None,
    }
    try:
        from app.memory.store import FileMemoryStore

        store = FileMemoryStore()
        data = store._load(user_key)  # noqa: SLF001 — admin read
    except Exception:
        return blank
    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        val = str(it.get("value") or it.get("text") or it.get("content") or "")
        items.append(
            {
                "id": str(it.get("id") or ""),
                "memory_type": str(it.get("memory_type") or it.get("type") or ""),
                "key": str(it.get("key") or ""),
                "value": val,
                "value_preview": val[:300],
                "score": float(it.get("score") or 0),
                "created_at": str(it.get("created_at") or ""),
                "updated_at": str(it.get("updated_at") or ""),
            }
        )
    items.sort(
        key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""),
        reverse=True,
    )
    partner_live = None
    try:
        from app.express_partner.partner_live_memory import load_partner_live_memory

        live = load_partner_live_memory(user_key)
        if isinstance(live, dict) and (live.get("summary") or live.get("updated_at")):
            partner_live = {
                "summary": str(live.get("summary") or "")[:500],
                "updated_at": str(live.get("updated_at") or ""),
            }
    except Exception:
        partner_live = None
    try:
        bytes_used = int(store.usage_bytes(user_key))
    except Exception:
        bytes_used = int(data.get("bytes_used") or 0)
    try:
        max_bytes = int(store.max_bytes())
    except Exception:
        max_bytes = int(data.get("max_bytes") or 0)
    return {
        "user_key": user_key,
        "user_masked": _mask_phone(user_key),
        "memory_items": items,
        "bytes_used": bytes_used,
        "bytes_label": _bytes_human(bytes_used),
        "max_bytes": max_bytes,
        "max_bytes_label": _bytes_human(max_bytes),
        "partner_live": partner_live,
    }


def list_system_memory() -> List[dict[str, Any]]:
    try:
        from app.memory.system_store import list_items

        return list_items()
    except Exception:
        return []


def lands_inventory_summary(*, sample_limit: int = 8) -> dict[str, Any]:
    """Read-only lands count + samples for memory page — no CRUD here."""
    blank: dict[str, Any] = {
        "count": 0,
        "ok": False,
        "samples": [],
        "by_status": {},
        "express_count": 0,
    }
    try:
        from app.utils.storage import data_dir

        path = os.path.join(data_dir(), "lands.json")
        if not os.path.isfile(path):
            fallback = os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), "..", "data", "lands.json"
                )
            )
            path = fallback if os.path.isfile(fallback) else path
        if not os.path.isfile(path):
            return blank
        with open(path, encoding="utf-8") as f:
            lands = json.load(f)
        items: list = []
        if isinstance(lands, list):
            items = lands
        elif isinstance(lands, dict):
            raw = lands.get("lands") or lands.get("items") or []
            items = raw if isinstance(raw, list) else []
        by_status: dict[str, int] = {}
        express_count = 0
        samples: list[dict[str, str]] = []
        limit = max(0, min(20, int(sample_limit or 8)))
        for land in items:
            if not isinstance(land, dict):
                continue
            status = str(land.get("status") or "unknown").strip() or "unknown"
            by_status[status] = int(by_status.get(status) or 0) + 1
            if land.get("is_express"):
                express_count += 1
            if len(samples) < limit:
                samples.append(
                    {
                        "code": str(land.get("code") or ""),
                        "title": str(land.get("title") or "")[:80],
                        "status": status,
                    }
                )
        return {
            "count": len(items),
            "ok": True,
            "samples": samples,
            "by_status": by_status,
            "express_count": express_count,
        }
    except Exception:
        return blank


def agent_goal_summary() -> dict[str, Any]:
    """Read-only goal one-liner + GOAL_SYSTEM excerpt (fail-open)."""
    blank: dict[str, Any] = {
        "ok": False,
        "one_liner": "",
        "system_excerpt": "",
        "role_fa": "",
        "identity": "",
        "geo_scope": "",
    }
    try:
        from app.ai import goal as goal_mod

        one = str(getattr(goal_mod, "GOAL_ONE_LINER", "") or "").strip()
        sys_txt = str(getattr(goal_mod, "GOAL_SYSTEM", "") or "").strip()
        excerpt = sys_txt[:320] + ("…" if len(sys_txt) > 320 else "")
        return {
            "ok": bool(one or excerpt),
            "one_liner": one,
            "system_excerpt": excerpt,
            "role_fa": str(getattr(goal_mod, "AGENT_ROLE_FA", "") or "").strip(),
            "identity": str(getattr(goal_mod, "AGENT_IDENTITY", "") or "").strip(),
            "geo_scope": str(getattr(goal_mod, "GEO_SCOPE_FA", "") or "").strip(),
        }
    except Exception:
        return blank


def knowledge_rag_status() -> dict[str, Any]:
    """Read-only RAG/knowledge status for system memory tab (fail-open)."""
    blank: dict[str, Any] = {
        "ok": False,
        "enabled": False,
        "index_exists": False,
        "index_path": "",
        "doc_count": 0,
        "top_k": 6,
    }
    try:
        from app.knowledge.rag.config import rag_enabled, rag_top_k_default

        enabled = bool(rag_enabled())
        top_k = int(rag_top_k_default())
    except Exception:
        enabled = False
        top_k = 6
    index_path = ""
    try:
        from app.knowledge.rag.vector_store import default_index_path

        index_path = str(default_index_path() or "")
    except Exception:
        index_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "instance",
                "data",
                "rag",
                "lands_index.json",
            )
        )
    index_exists = bool(index_path and os.path.isfile(index_path))
    doc_count = 0
    if index_exists:
        try:
            with open(index_path, encoding="utf-8") as f:
                idx = json.load(f)
            if isinstance(idx, dict):
                vectors = idx.get("vectors")
                meta = idx.get("meta")
                if isinstance(vectors, dict):
                    doc_count = len(vectors)
                elif isinstance(meta, dict):
                    doc_count = len(meta)
        except Exception:
            doc_count = 0
    return {
        "ok": True,
        "enabled": enabled,
        "index_exists": index_exists,
        "index_path": index_path,
        "doc_count": doc_count,
        "top_k": top_k,
    }


def upsert_user_memory(
    user_key: str,
    *,
    key: str,
    value: str,
    memory_type: str = "long_term",
) -> dict[str, Any]:
    uk = (user_key or "").strip()
    k = (key or "").strip()
    v = (value or "").strip()
    if not uk or not k or not v:
        return {"ok": False, "error": "user_key، key و value لازم است."}
    try:
        import uuid

        from app.memory.di import make_memory_store
        from app.memory.interfaces import MEMORY_LONG, MEMORY_TYPES, MemoryItem

        mt = (memory_type or MEMORY_LONG).strip() or MEMORY_LONG
        if mt not in MEMORY_TYPES:
            mt = MEMORY_LONG
        store = make_memory_store()
        item = MemoryItem(
            id=str(uuid.uuid4()),
            user_key=uk,
            memory_type=mt,
            key=k,
            value=v,
            score=1.0,
            metadata={"source": "admin_console"},
        )
        saved = store.upsert(item)
        try:
            from app.hardening.audit import record_admin_audit

            record_admin_audit(
                action="ai_memory_user_upsert",
                entity_type="ai_memory_user",
                entity_id=uk[:32],
                summary=f"Upsert user memory key={k[:64]}",
            )
        except Exception:
            pass
        return {
            "ok": True,
            "id": saved.id,
            "key": saved.key,
            "memory_type": saved.memory_type,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def delete_user_memory_item(user_key: str, memory_id: str) -> dict[str, Any]:
    uk = (user_key or "").strip()
    mid = (memory_id or "").strip()
    if not uk or not mid:
        return {"ok": False, "error": "user_key و id لازم است."}
    try:
        from app.memory.service import forget_memories

        out = forget_memories(uk, memory_ids=[mid])
        if out.get("ok") and int(out.get("deleted") or 0) > 0:
            try:
                from app.hardening.audit import record_admin_audit

                record_admin_audit(
                    action="ai_memory_user_delete",
                    entity_type="ai_memory_user",
                    entity_id=uk[:32],
                    summary=f"Deleted user memory id={mid[:36]}",
                )
            except Exception:
                pass
            return {"ok": True, "deleted": int(out.get("deleted") or 0)}
        return {"ok": False, "error": out.get("error") or "آیتم یافت نشد."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def wipe_user_memory(user_key: str) -> dict[str, Any]:
    uk = (user_key or "").strip()
    if not uk:
        return {"ok": False, "error": "user_key لازم است."}
    try:
        from app.memory.di import make_memory_store
        from app.memory.service import forget_memories

        store = make_memory_store()
        ids = [it.id for it in (store.list_items(uk) or []) if it.id]
        out = forget_memories(uk, memory_ids=ids) if ids else {"ok": True, "deleted": 0}
        if out.get("ok"):
            try:
                from app.hardening.audit import record_admin_audit

                record_admin_audit(
                    action="ai_memory_user_wipe",
                    entity_type="ai_memory_user",
                    entity_id=uk[:32],
                    summary=f"Wiped user memory ({int(out.get('deleted') or 0)} items)",
                )
            except Exception:
                pass
            return {"ok": True, "deleted": int(out.get("deleted") or 0)}
        return {"ok": False, "error": out.get("error") or "پاک‌سازی ناموفق."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def add_system_memory(key: str, value: str) -> dict[str, Any]:
    try:
        from app.memory.system_store import add

        row = add(key, value)
        if not row:
            return {"ok": False, "error": "کلید و متن لازم است."}
        try:
            from app.hardening.audit import record_admin_audit

            record_admin_audit(
                action="ai_memory_system_add",
                entity_type="ai_memory_system",
                entity_id=str(row.get("id") or "")[:36],
                summary=f"Added system memory key={str(row.get('key') or '')[:64]}",
            )
        except Exception:
            pass
        return {"ok": True, "item": row}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def delete_system_memory(item_id: str) -> dict[str, Any]:
    try:
        from app.memory.system_store import delete

        ok = delete(item_id)
        if ok:
            try:
                from app.hardening.audit import record_admin_audit

                record_admin_audit(
                    action="ai_memory_system_delete",
                    entity_type="ai_memory_system",
                    entity_id=str(item_id or "")[:36],
                    summary="Deleted system memory item",
                )
            except Exception:
                pass
            return {"ok": True}
        return {"ok": False, "error": "آیتم یافت نشد."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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
