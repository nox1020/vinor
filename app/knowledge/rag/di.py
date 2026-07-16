from __future__ import annotations

from app.knowledge.interfaces import EmbeddingProvider, VectorStore

from .config import (
    embedding_api_key,
    embedding_base_url,
    embedding_model_name,
    embedding_provider_name,
    vector_store_name,
)
from .embedding_providers import (
    BGEEmbeddingProvider,
    DeepSeekEmbeddingProvider,
    JinaEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from .vector_stores import ChromaVectorStore, FaissVectorStore, InMemoryVectorStore, QdrantVectorStore


def make_embedding_provider() -> EmbeddingProvider:
    name = embedding_provider_name()
    base = embedding_base_url()
    key = embedding_api_key()
    model = embedding_model_name()
    if name == "openai":
        return OpenAIEmbeddingProvider(base_url=base, api_key=key, model=model)
    if name == "bge":
        return BGEEmbeddingProvider(base_url=base, api_key=key, model=model)
    if name == "jina":
        return JinaEmbeddingProvider(base_url=base, api_key=key, model=model)
    # default production path
    return DeepSeekEmbeddingProvider(base_url=base, api_key=key, model=model)


def make_vector_store() -> VectorStore:
    name = vector_store_name()
    if name == "faiss":
        return FaissVectorStore()
    if name == "qdrant":
        return QdrantVectorStore()
    if name == "chroma":
        return ChromaVectorStore()
    return InMemoryVectorStore()

