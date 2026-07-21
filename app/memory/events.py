"""رویدادهای فروش → حافظهٔ درجه۱ (بازدید / معامله / تماس / رد)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.memory.interfaces import (
    MEMORY_RELATIONSHIP,
    MEMORY_SHORT,
    MemoryItem,
)

# انواع رویداد فروش
EVENT_VISIT = "visit"
EVENT_VISIT_DONE = "visit_done"
EVENT_DEAL = "deal"
EVENT_DEAL_RELEASE = "deal_release"
EVENT_CALL = "call"
EVENT_FOLLOWUP = "followup"
EVENT_LIKED = "liked"
EVENT_REJECTED = "rejected"
EVENT_VIEWED = "viewed"

_EVENT_LABELS = {
    EVENT_VISIT: "بازدید ثبت شد",
    EVENT_VISIT_DONE: "بازدید انجام شد",
    EVENT_DEAL: "معامله شروع شد",
    EVENT_DEAL_RELEASE: "معامله بسته/آزاد شد",
    EVENT_CALL: "تماس ثبت شد",
    EVENT_FOLLOWUP: "پیگیری زمان‌بندی شد",
    EVENT_LIKED: "علاقه‌مند به فایل",
    EVENT_REJECTED: "فایل رد شد",
    EVENT_VIEWED: "فایل مشاهده شد",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_land(code: str) -> str:
    return str(code or "").strip()


def record_sales_event(
    user_key: str,
    event: str,
    *,
    land_code: str = "",
    detail: str = "",
    audience: str = "",
    metadata: dict[str, Any] | None = None,
) -> MemoryItem | None:
    """ثبت ایمن رویداد فروش در ai_memory — هرگز exception به caller پرتاب نمی‌کند."""
    uk = str(user_key or "").strip()
    ev = str(event or "").strip().lower()
    if not uk or not ev:
        return None
    try:
        from app.memory.config import memory_enabled
        from app.memory.di import make_memory_store
        from app.memory.lifecycle import resolve_conflicts

        if not memory_enabled():
            return None

        land = _norm_land(land_code)
        label = _EVENT_LABELS.get(ev, ev)
        if land and ev in (
            EVENT_VISIT,
            EVENT_VISIT_DONE,
            EVENT_DEAL,
            EVENT_DEAL_RELEASE,
            EVENT_LIKED,
            EVENT_REJECTED,
            EVENT_VIEWED,
        ):
            key = f"{ev}:{land}"
            value = f"{label}: {land}"
            if detail:
                value = f"{value} — {detail.strip()[:80]}"
        else:
            key = f"event:{ev}"
            value = label
            if land:
                value = f"{value} ({land})"
            if detail:
                value = f"{value} — {detail.strip()[:80]}"

        meta: dict[str, Any] = {
            "source": "sales_event",
            "event": ev,
            "audience": audience or "",
        }
        if land:
            meta["land_code"] = land
            meta["relation"] = ev
        if metadata:
            meta.update({k: v for k, v in metadata.items() if v is not None})

        item = MemoryItem(
            id=str(uuid.uuid4()),
            user_key=uk,
            memory_type=MEMORY_RELATIONSHIP,
            key=key,
            value=value[:200],
            score=0.92 if ev in (EVENT_DEAL, EVENT_VISIT_DONE, EVENT_VISIT) else 0.85,
            metadata=meta,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        store = make_memory_store()
        resolve_conflicts(store, item)
        saved = store.upsert(item)

        # short-term: آخرین رویداد فروش
        short = MemoryItem(
            id=str(uuid.uuid4()),
            user_key=uk,
            memory_type=MEMORY_SHORT,
            key="last_sales_event",
            value=saved.value[:100],
            score=0.7,
            metadata={"event": ev, "land_code": land, "audience": audience or ""},
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        resolve_conflicts(store, short)
        store.upsert(short)
        return saved
    except Exception:
        return None
