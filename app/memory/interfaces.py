from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


MEMORY_SHORT = "short_term"
MEMORY_LONG = "long_term"
MEMORY_SEMANTIC = "semantic"
MEMORY_RELATIONSHIP = "relationship"

MEMORY_TYPES = (
    MEMORY_SHORT,
    MEMORY_LONG,
    MEMORY_SEMANTIC,
    MEMORY_RELATIONSHIP,
)


@dataclass(frozen=True)
class MemoryItem:
    id: str
    user_key: str
    memory_type: str
    key: str
    value: str
    score: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class MemoryRetrieveRequest:
    user_key: str
    query: str
    audience: str = ""
    thread_id: str | None = None
    budget_chars: int = 280
    top_k: int = 8


@dataclass(frozen=True)
class MemoryRetrieveResult:
    items: list[MemoryItem]
    text: str
    retrieved_count: int
    used_count: int
    memory_tokens: int


@dataclass(frozen=True)
class MemoryExtractRequest:
    user_key: str
    user_message: str
    assistant_reply: str
    audience: str = ""
    thread_id: str | None = None
    land_codes: tuple[str, ...] = ()


class MemoryStore(Protocol):
    def list_items(self, user_key: str, *, memory_type: str | None = None) -> list[MemoryItem]:
        ...

    def upsert(self, item: MemoryItem) -> MemoryItem:
        ...

    def delete(self, user_key: str, memory_id: str) -> bool:
        ...

    def update(self, user_key: str, memory_id: str, *, value: str | None = None, metadata: dict[str, Any] | None = None) -> MemoryItem | None:
        ...


class MemoryExtractor(Protocol):
    def extract(self, req: MemoryExtractRequest) -> list[MemoryItem]:
        ...


class MemoryRetriever(Protocol):
    def retrieve(self, req: MemoryRetrieveRequest) -> MemoryRetrieveResult:
        ...


class MemorySummarizer(Protocol):
    def summarize(self, items: list[MemoryItem], *, budget_chars: int) -> str:
        ...


class MemoryManager(Protocol):
    def retrieve_for_prompt(self, req: MemoryRetrieveRequest) -> MemoryRetrieveResult:
        ...

    def ingest_exchange(self, req: MemoryExtractRequest) -> list[MemoryItem]:
        ...

    def delete_memory(self, user_key: str, memory_id: str) -> bool:
        ...

    def edit_memory(self, user_key: str, memory_id: str, *, value: str) -> MemoryItem | None:
        ...


class MemoryProvider(Protocol):
    """Facade used by AI layer; hides store/extractor/retriever internals."""

    def get_prompt_memory(self, req: MemoryRetrieveRequest) -> MemoryRetrieveResult:
        ...

    def learn_from_exchange(self, req: MemoryExtractRequest) -> list[MemoryItem]:
        ...
