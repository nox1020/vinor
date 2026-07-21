from __future__ import annotations

from app.memory.interfaces import (
    MemoryExtractRequest,
    MemoryExtractor,
    MemoryItem,
    MemoryManager,
    MemoryProvider,
    MemoryRetrieveRequest,
    MemoryRetrieveResult,
    MemoryRetriever,
    MemoryStore,
)
from app.memory.lifecycle import purge_expired, resolve_conflicts


class DefaultMemoryManager(MemoryManager):
    def __init__(
        self,
        *,
        store: MemoryStore,
        extractor: MemoryExtractor,
        retriever: MemoryRetriever,
    ):
        self._store = store
        self._extractor = extractor
        self._retriever = retriever

    def retrieve_for_prompt(self, req: MemoryRetrieveRequest) -> MemoryRetrieveResult:
        try:
            purge_expired(self._store, req.user_key)
        except Exception:
            pass
        return self._retriever.retrieve(req)

    def ingest_exchange(self, req: MemoryExtractRequest) -> list[MemoryItem]:
        extracted = self._extractor.extract(req)
        saved: list[MemoryItem] = []
        for item in extracted:
            if not (item.value or "").strip():
                continue
            try:
                resolve_conflicts(self._store, item)
            except Exception:
                pass
            saved.append(self._store.upsert(item))
        return saved

    def delete_memory(self, user_key: str, memory_id: str) -> bool:
        return self._store.delete(user_key, memory_id)

    def edit_memory(self, user_key: str, memory_id: str, *, value: str) -> MemoryItem | None:
        return self._store.update(user_key, memory_id, value=value)


class DefaultMemoryProvider(MemoryProvider):
    """AI-facing facade — Agent/Prompt never talk to store directly."""

    def __init__(self, manager: MemoryManager):
        self._manager = manager

    def get_prompt_memory(self, req: MemoryRetrieveRequest) -> MemoryRetrieveResult:
        return self._manager.retrieve_for_prompt(req)

    def learn_from_exchange(self, req: MemoryExtractRequest) -> list[MemoryItem]:
        return self._manager.ingest_exchange(req)
