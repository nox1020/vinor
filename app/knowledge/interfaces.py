from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    top_k: int = 6
    allowed_codes: tuple[str, ...] = ()


class PropertyRetriever(Protocol):
    """Interface used by AI context layer to select relevant properties."""

    def retrieve_property_codes(self, req: RetrievalRequest) -> list[str]:
        ...


class EmbeddingProvider(Protocol):
    """Pluggable embedding provider; retriever is source-agnostic."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class VectorRow:
    id: str
    vector: list[float]
    metadata: dict[str, Any]


class VectorStore(Protocol):
    """Pluggable vector store; backend can be swapped with DI."""

    def rebuild(self, rows: list[VectorRow]) -> None:
        ...

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        allowed_ids: set[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[str]:
        ...

