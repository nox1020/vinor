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

_TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]{2,}", re.I)


class DynamicMemoryRetriever(MemoryRetriever):
    """Retrieve only query-relevant memories within token/char budget."""

    def __init__(self, store: MemoryStore, summarizer: MemorySummarizer):
        self._store = store
        self._summarizer = summarizer

    def retrieve(self, req: MemoryRetrieveRequest) -> MemoryRetrieveResult:
        query = (req.query or "").strip()
        all_items = self._store.list_items(req.user_key)
        if not all_items:
            return MemoryRetrieveResult([], "", 0, 0, 0)

        scored = sorted(
            ((_score_item(it, query), it) for it in all_items),
            key=lambda x: x[0],
            reverse=True,
        )
        # Drop weak matches for general chat
        selected: list[MemoryItem] = []
        for score, it in scored:
            if score < 0.15 and query:
                # keep sticky long-term prefs lightly if query is property-related
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


def _score_item(item: MemoryItem, query: str) -> float:
    q = (query or "").strip().lower()
    base = float(item.score or 0.5)
    if not q:
        # without query only short/long lightly
        if item.memory_type in (MEMORY_SHORT, MEMORY_LONG):
            return base * 0.4
        return 0.05

    text = f"{item.key} {item.value}".lower()
    tokens = set(_TOKEN_RE.findall(q))
    hit = sum(1 for t in tokens if t in text)
    overlap = hit / max(1, len(tokens))

    type_boost = {
        MEMORY_SHORT: 0.15,
        MEMORY_LONG: 0.25,
        MEMORY_SEMANTIC: 0.2,
        MEMORY_RELATIONSHIP: 0.3 if any(k in q for k in ("فایل", "ملک", "ویلا", "زمین", "کد")) else 0.05,
    }.get(item.memory_type, 0.1)

    # Prefer land-code matches
    code = str((item.metadata or {}).get("land_code") or "")
    if code and code.lower() in q:
        type_boost += 0.4

    return base * 0.5 + overlap * 0.8 + type_boost


def _items_used_in_text(items: list[MemoryItem], text: str) -> list[MemoryItem]:
    if not text:
        return []
    used = []
    for it in items:
        if it.value and it.value in text:
            used.append(it)
    return used
