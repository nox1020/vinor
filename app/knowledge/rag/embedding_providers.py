from __future__ import annotations

from typing import Any

import requests

from app.knowledge.interfaces import EmbeddingProvider


class HttpEmbeddingProvider(EmbeddingProvider):
    """Generic HTTP embedding provider (OpenAI/DeepSeek/Jina compatible)."""

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout_sec: int = 20):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout_sec = max(5, int(timeout_sec))

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.base_url or not self.api_key or not self.model:
            raise RuntimeError("Embedding provider is not configured.")
        if not texts:
            return []
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "input": texts}
        r = requests.post(url, headers=headers, json=payload, timeout=self.timeout_sec)
        r.raise_for_status()
        data = r.json()
        out = _extract_embeddings(data)
        if len(out) != len(texts):
            raise RuntimeError("Embedding response size mismatch.")
        return out


class OpenAIEmbeddingProvider(HttpEmbeddingProvider):
    pass


class DeepSeekEmbeddingProvider(HttpEmbeddingProvider):
    pass


class BGEEmbeddingProvider(HttpEmbeddingProvider):
    pass


class JinaEmbeddingProvider(HttpEmbeddingProvider):
    pass


def _extract_embeddings(data: Any) -> list[list[float]]:
    # OpenAI-like schema
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        out: list[list[float]] = []
        for row in data["data"]:
            if isinstance(row, dict) and isinstance(row.get("embedding"), list):
                out.append([float(x) for x in row["embedding"]])
        if out:
            return out
    # Generic schema
    if isinstance(data, dict) and isinstance(data.get("embeddings"), list):
        return [[float(x) for x in row] for row in data["embeddings"] if isinstance(row, list)]
    raise RuntimeError("Unknown embedding response schema.")

