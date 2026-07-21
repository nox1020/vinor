from __future__ import annotations

import re

from app.ai.token_analytics import estimate_tokens
from app.memory.interfaces import (
    MEMORY_LONG,
    MEMORY_RELATIONSHIP,
    MEMORY_SEMANTIC,
    MEMORY_SHORT,
    MemoryItem,
    MemoryRetrieveRequest,
    MemoryRetrieveResult,
    MemoryRetriever,
    MemoryStore,
    MemorySummarizer,
)
from app.memory.lifecycle import filter_active

_TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]{2,}", re.I)

_STAGE_VISIT = frozenset({"visit", "negotiate", "deal"})
_STAGE_SEARCH = frozenset({"search", "buy", "general", "land", ""})
_STAGE_SELL = frozenset({"sell", "partner"})


class DynamicMemoryRetriever(MemoryRetriever):
    """Retrieve only query-relevant memories within token/char budget."""

    def __init__(self, store: MemoryStore, summarizer: MemorySummarizer):
        self._store = store
        self._summarizer = summarizer

    def retrieve(self, req: MemoryRetrieveRequest) -> MemoryRetrieveResult:
        query = (req.query or "").strip()
        all_items = filter_active(self._store.list_items(req.user_key) or [])
        if not all_items:
            return MemoryRetrieveResult([], "", 0, 0, 0)

        stage = (req.stage or "").strip().lower()
        scored = sorted(
            ((_score_item(it, query, stage=stage), it) for it in all_items),
            key=lambda x: x[0],
            reverse=True,
        )
        selected: list[MemoryItem] = []
        for score, it in scored:
            if score < 0.15 and query:
                if it.memory_type != MEMORY_LONG:
                    continue
            selected.append(it)
            if len(selected) >= max(1, req.top_k):
                break

        text = self._summarizer.summarize(selected, budget_chars=req.budget_chars)
        used = _items_used_in_text(selected, text)
        return MemoryRetrieveResult(
            items=selected,
            text=text,
            retrieved_count=len(selected),
            used_count=len(used),
            memory_tokens=estimate_tokens(text) if text else 0,
        )


def _score_item(item: MemoryItem, query: str, *, stage: str = "") -> float:
    q = (query or "").strip().lower()
    base = float(item.score or 0.5)
    stage_boost = _stage_boost(item, stage)

    if not q:
        if item.memory_type in (MEMORY_SHORT, MEMORY_LONG):
            return base * 0.4 + stage_boost
        if item.memory_type == MEMORY_RELATIONSHIP and stage in _STAGE_VISIT:
            return base * 0.45 + stage_boost
        return 0.05 + stage_boost * 0.5

    text = f"{item.key} {item.value}".lower()
    tokens = set(_TOKEN_RE.findall(q))
    hit = sum(1 for t in tokens if t in text)
    overlap = hit / max(1, len(tokens))

    type_boost = {
        MEMORY_SHORT: 0.15,
        MEMORY_LONG: 0.25,
        MEMORY_SEMANTIC: 0.2,
        MEMORY_RELATIONSHIP: 0.3
        if any(k in q for k in ("فایل", "ملک", "ویلا", "زمین", "کد", "بازدید", "معامله"))
        else 0.05,
    }.get(item.memory_type, 0.1)

    code = str((item.metadata or {}).get("land_code") or "")
    if code and code.lower() in q:
        type_boost += 0.4

    # رویداد فروش همیشه کمی بالاتر
    if str((item.metadata or {}).get("source") or "") == "sales_event":
        type_boost += 0.12

    return base * 0.5 + overlap * 0.8 + type_boost + stage_boost


def _stage_boost(item: MemoryItem, stage: str) -> float:
    st = (stage or "").strip().lower()
    mtype = item.memory_type
    key = str(item.key or "")
    if st in _STAGE_VISIT:
        if mtype == MEMORY_RELATIONSHIP:
            return 0.22
        if key.startswith(("visit", "deal", "liked", "call", "followup", "event:")):
            return 0.18
        if mtype == MEMORY_SHORT and key == "last_sales_event":
            return 0.15
    if st in _STAGE_SEARCH:
        if mtype == MEMORY_LONG:
            return 0.18
        if key in ("budget",) or key.startswith(("city:", "category:", "pref:")):
            return 0.2
    if st in _STAGE_SELL:
        if mtype == MEMORY_RELATIONSHIP or key == "live_summary":
            return 0.15
    return 0.0


def _items_used_in_text(items: list[MemoryItem], text: str) -> list[MemoryItem]:
    if not text:
        return []
    used = []
    for it in items:
        if it.value and it.value in text:
            used.append(it)
    return used
