from __future__ import annotations

import os


def rag_enabled() -> bool:
    return (os.environ.get("VINOR_RAG_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def rag_top_k_default() -> int:
    try:
        return max(1, min(20, int(os.environ.get("VINOR_RAG_TOP_K") or 6)))
    except Exception:
        return 6


def rag_cache_ttl_sec() -> int:
    try:
        return max(5, min(3600, int(os.environ.get("VINOR_RAG_CACHE_TTL_SEC") or 120)))
    except Exception:
        return 120


def embedding_provider_name() -> str:
    return (os.environ.get("VINOR_EMBEDDING_PROVIDER") or "deepseek").strip().lower()


def vector_store_name() -> str:
    return (os.environ.get("VINOR_VECTOR_STORE") or "inmemory").strip().lower()


def embedding_model_name() -> str:
    return (os.environ.get("VINOR_EMBEDDING_MODEL") or "").strip()


def embedding_base_url() -> str:
    return (os.environ.get("VINOR_EMBEDDING_BASE_URL") or "").strip()


def embedding_api_key() -> str:
    return (os.environ.get("VINOR_EMBEDDING_API_KEY") or "").strip()

