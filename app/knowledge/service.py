from __future__ import annotations

import threading

from app.knowledge.interfaces import PropertyRetriever
from app.knowledge.rag.config import rag_enabled
from app.knowledge.rag.retriever import LandsRagRetriever

_LOCK = threading.Lock()
_RETRIEVER: PropertyRetriever | None = None


def get_property_retriever() -> PropertyRetriever | None:
    global _RETRIEVER
    if not rag_enabled():
        return None
    if _RETRIEVER is not None:
        return _RETRIEVER
    with _LOCK:
        if _RETRIEVER is None:
            _RETRIEVER = LandsRagRetriever()
    return _RETRIEVER

