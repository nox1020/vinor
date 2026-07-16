from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from app.knowledge.interfaces import PropertyRetriever, RetrievalRequest, VectorRow

from .cache import TTLCache
from .config import rag_cache_ttl_sec
from .di import make_embedding_provider, make_vector_store
from .query_analysis import analyze_query
from .sources import load_land_documents
from .vector_store import LandsVectorStore, default_index_path, lands_source_mtime


class TfidfFallbackRetriever(PropertyRetriever):
    """Fallback-only retriever for dev/offline mode."""

    def __init__(self, index_path: str | None = None):
        self._store = LandsVectorStore(index_path or default_index_path())
        self._lock = threading.Lock()
        self._cache = TTLCache(ttl_sec=rag_cache_ttl_sec())

    def ensure_index(self) -> None:
        mtime = lands_source_mtime()
        if not self._store.needs_rebuild(mtime):
            return
        with self._lock:
            if not self._store.needs_rebuild(mtime):
                return
            docs = load_land_documents()
            self._store.build(docs, source_mtime=mtime)

    def retrieve_property_codes(self, req: RetrievalRequest) -> list[str]:
        q = (req.query or "").strip()
        if not q:
            return []
        self.ensure_index()
        signals = analyze_query(q)
        allowed = set(req.allowed_codes or ())
        key = _cache_key(q, req.top_k, allowed, signals.metadata_filter)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        out = self._store.query(
            q,
            top_k=max(1, req.top_k),
            allowed_codes=allowed if allowed else None,
            metadata_filter=signals.metadata_filter,
        )
        self._cache.set(key, out)
        return out


class LandsRagRetriever(PropertyRetriever):
    """Production path: embedding-provider + vector-store via DI."""

    def __init__(self):
        self._provider = make_embedding_provider()
        self._vector_store = make_vector_store()
        self._fallback = TfidfFallbackRetriever()
        self._cache = TTLCache(ttl_sec=rag_cache_ttl_sec())
        self._lock = threading.Lock()
        self._indexed = False
        self._source_mtime = 0.0
        self._row_cache: dict[str, VectorRow] = {}
        self._sig_cache: dict[str, str] = {}
        self._embed_cache: dict[str, list[float]] = {}

    def _ensure_index(self) -> None:
        source_mtime = lands_source_mtime()
        if self._indexed and source_mtime <= self._source_mtime:
            return
        with self._lock:
            if self._indexed and source_mtime <= self._source_mtime:
                return
            docs = load_land_documents()
            if not docs:
                self._vector_store.rebuild([])
                self._indexed = True
                self._source_mtime = source_mtime
                return
            cur_codes = {d.code for d in docs}
            # delete removed rows
            for code in list(self._row_cache.keys()):
                if code not in cur_codes:
                    self._row_cache.pop(code, None)
                    self._sig_cache.pop(code, None)
            changed_docs: list[Any] = []
            for d in docs:
                sig = _doc_signature(d)
                if self._sig_cache.get(d.code) != sig:
                    changed_docs.append(d)
                    self._sig_cache[d.code] = sig
            if changed_docs:
                vecs = self._embed_texts_cached([d.text for d in changed_docs])
                for i, d in enumerate(changed_docs):
                    self._row_cache[d.code] = VectorRow(
                        id=d.code,
                        vector=vecs[i],
                        metadata={
                            "code": d.code,
                            "city": d.city,
                            "location": d.location,
                            "category": d.category,
                            "status": d.status,
                            "tags": d.tags,
                            "price_total": d.price_total,
                            "area_total": d.area_total,
                        },
                    )
            self._vector_store.rebuild(list(self._row_cache.values()))
            self._indexed = True
            self._source_mtime = source_mtime

    def ensure_index(self) -> None:
        """Public warm-up hook for scripts/startup."""
        try:
            self._ensure_index()
        except Exception:
            # Warm-up should never break app startup; runtime has fallback.
            pass

    def retrieve_property_codes(self, req: RetrievalRequest) -> list[str]:
        q = (req.query or "").strip()
        if not q:
            return []
        signals = analyze_query(q)
        allowed = set(req.allowed_codes or ())
        key = _cache_key(q, req.top_k, allowed, signals.metadata_filter)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            self._ensure_index()
            qvec_list = self._embed_texts_cached([q])
            qvec = qvec_list[0] if qvec_list else []
            if not qvec:
                raise RuntimeError("empty query embedding")
            dyn_top_k = _dynamic_top_k(q, req.top_k)
            out = self._vector_store.search(
                qvec,
                top_k=dyn_top_k,
                allowed_ids=allowed if allowed else None,
                metadata_filter=signals.metadata_filter,
            )
        except Exception:
            out = self._fallback.retrieve_property_codes(req)
        self._cache.set(key, out)
        return out

    def _embed_texts_cached(self, texts: list[str]) -> list[list[float]]:
        missing: list[str] = []
        for t in texts:
            h = _text_hash(t)
            if h not in self._embed_cache:
                missing.append(t)
        if missing:
            vecs = self._provider.embed_texts(missing)
            for i, t in enumerate(missing):
                self._embed_cache[_text_hash(t)] = vecs[i]
            # cap memory
            if len(self._embed_cache) > 4000:
                for k in list(self._embed_cache.keys())[:1000]:
                    self._embed_cache.pop(k, None)
        return [self._embed_cache.get(_text_hash(t), []) for t in texts]


def _cache_key(query: str, top_k: int, allowed: set[str], filt: dict[str, Any]) -> str:
    payload = {
        "q": query.strip().lower(),
        "k": int(top_k),
        "allowed": sorted(allowed),
        "f": filt,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _doc_signature(doc: Any) -> str:
    raw = json.dumps(
        {
            "code": getattr(doc, "code", ""),
            "text": getattr(doc, "text", ""),
            "city": getattr(doc, "city", ""),
            "location": getattr(doc, "location", ""),
            "category": getattr(doc, "category", ""),
            "status": getattr(doc, "status", ""),
            "tags": getattr(doc, "tags", []),
            "price_total": getattr(doc, "price_total", 0),
            "area_total": getattr(doc, "area_total", 0),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()


def _dynamic_top_k(query: str, requested: int) -> int:
    q = (query or "").strip()
    base = max(1, int(requested or 6))
    if len(q) <= 10:
        return min(4, base)
    if len(q) <= 32:
        return min(6, max(3, base))
    return min(10, max(4, base))

