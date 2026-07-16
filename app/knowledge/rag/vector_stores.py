from __future__ import annotations

import math
from typing import Any

from app.knowledge.interfaces import VectorRow, VectorStore


class InMemoryVectorStore(VectorStore):
    def __init__(self):
        self._rows: dict[str, VectorRow] = {}

    def rebuild(self, rows: list[VectorRow]) -> None:
        self._rows = {r.id: r for r in rows}

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        allowed_ids: set[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[str]:
        q = _normalize(query_vector)
        scored: list[tuple[float, str]] = []
        for rid, row in self._rows.items():
            if allowed_ids is not None and rid not in allowed_ids:
                continue
            if not _meta_match(row.metadata, metadata_filter or {}):
                continue
            sim = _cosine(q, _normalize(row.vector))
            if sim <= 0:
                continue
            scored.append((sim + _lexical_boost(str(row.metadata.get("text") or ""), row.metadata), rid))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [rid for _, rid in scored[: max(1, top_k)]]


class FaissVectorStore(InMemoryVectorStore):
    """Adapter placeholder; currently uses in-memory backend."""


class QdrantVectorStore(InMemoryVectorStore):
    """Adapter placeholder; currently uses in-memory backend."""


class ChromaVectorStore(InMemoryVectorStore):
    """Adapter placeholder; currently uses in-memory backend."""


def _normalize(v: list[float]) -> list[float]:
    n2 = sum(x * x for x in v)
    if n2 <= 0:
        return v
    d = math.sqrt(n2)
    return [x / d for x in v]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    s = 0.0
    for i in range(n):
        s += a[i] * b[i]
    return s


def _lexical_boost(query_text: str, meta: dict[str, Any]) -> float:
    q = str(query_text or "").strip().lower()
    if not q:
        return 0.0
    code = str(meta.get("code") or "").lower()
    city = str(meta.get("city") or "").lower()
    category = str(meta.get("category") or "").lower()
    score = 0.0
    if code and code in q:
        score += 0.2
    if city and city in q:
        score += 0.06
    if category and category in q:
        score += 0.06
    return score


def _meta_match(meta: dict[str, Any], filt: dict[str, Any]) -> bool:
    if not filt:
        return True
    city = str(meta.get("city") or "").lower()
    category = str(meta.get("category") or "").lower()
    status = str(meta.get("status") or "").lower()
    price = int(meta.get("price_total") or 0)
    area = int(meta.get("area_total") or 0)
    tags = set(str(x).lower() for x in (meta.get("tags") or []) if str(x).strip())
    wanted_city = str(filt.get("city") or "").strip().lower()
    if wanted_city and wanted_city not in city:
        return False
    wanted_category = str(filt.get("category") or "").strip().lower()
    if wanted_category and wanted_category not in category:
        return False
    wanted_status = str(filt.get("status") or "").strip().lower()
    if wanted_status and wanted_status != status:
        return False
    max_price = int(filt.get("max_price") or 0)
    if max_price > 0 and (price <= 0 or price > max_price):
        return False
    min_area = int(filt.get("min_area") or 0)
    if min_area > 0 and area < min_area:
        return False
    required_tags = set(str(x).lower() for x in (filt.get("tags") or []) if str(x).strip())
    if required_tags and not (required_tags & tags):
        return False
    return True

