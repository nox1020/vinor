from __future__ import annotations

from app.memory.config import memory_store_backend
from app.memory.extractor import RuleMemoryExtractor
from app.memory.interfaces import MemoryManager, MemoryProvider
from app.memory.manager import DefaultMemoryManager, DefaultMemoryProvider
from app.memory.retriever import DynamicMemoryRetriever
from app.memory.store import FileMemoryStore, InMemoryMemoryStore
from app.memory.summarizer import CompactMemorySummarizer


def make_memory_store():
    name = memory_store_backend()
    if name in ("memory", "inmemory"):
        return InMemoryMemoryStore()
    # Default production path: file store (Redis/Postgres adapters can replace later)
    return FileMemoryStore()


def make_memory_manager() -> MemoryManager:
    store = make_memory_store()
    summarizer = CompactMemorySummarizer()
    retriever = DynamicMemoryRetriever(store, summarizer)
    extractor = RuleMemoryExtractor()
    return DefaultMemoryManager(store=store, extractor=extractor, retriever=retriever)


def make_memory_provider() -> MemoryProvider:
    return DefaultMemoryProvider(make_memory_manager())
