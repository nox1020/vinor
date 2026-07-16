from __future__ import annotations

import unittest
from unittest.mock import patch

from app.knowledge.interfaces import RetrievalRequest, VectorStore
from app.knowledge.rag.models import LandDocument
from app.knowledge.rag.retriever import LandsRagRetriever


class _FakeProvider:
    def embed_texts(self, texts):
        out = []
        for t in texts:
            if "ویلا" in t:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out


class _FailingProvider:
    def embed_texts(self, texts):
        raise RuntimeError("provider unavailable")


class _FakeStore(VectorStore):
    def __init__(self):
        self.rows = []

    def rebuild(self, rows):
        self.rows = rows

    def search(self, query_vector, *, top_k, allowed_ids=None, metadata_filter=None):
        ids = [r.id for r in self.rows]
        return ids[:top_k]


class RagDiRetrieverTests(unittest.TestCase):
    def test_primary_embedding_path(self):
        docs = [
            LandDocument("V-10", "ویلا دماوند", "دماوند", "گرمابسرد", "ویلا", "active", [], 10, 300),
            LandDocument("Z-22", "زمین تهران", "تهران", "لواسان", "زمین", "active", [], 20, 500),
        ]
        with patch("app.knowledge.rag.retriever.make_embedding_provider", return_value=_FakeProvider()), patch(
            "app.knowledge.rag.retriever.make_vector_store", return_value=_FakeStore()
        ), patch("app.knowledge.rag.retriever.load_land_documents", return_value=docs), patch(
            "app.knowledge.rag.retriever.lands_source_mtime", return_value=1.0
        ):
            r = LandsRagRetriever()
            out = r.retrieve_property_codes(RetrievalRequest(query="ویلا", top_k=1))
            self.assertEqual(out, ["V-10"])

    def test_fallback_when_provider_fails(self):
        docs = [LandDocument("X-1", "ویلا", "دماوند", "گرمابسرد", "ویلا", "active", [], 1, 1)]
        with patch("app.knowledge.rag.retriever.make_embedding_provider", return_value=_FailingProvider()), patch(
            "app.knowledge.rag.retriever.make_vector_store", return_value=_FakeStore()
        ), patch("app.knowledge.rag.retriever.load_land_documents", return_value=docs), patch(
            "app.knowledge.rag.retriever.lands_source_mtime", return_value=1.0
        ), patch(
            "app.knowledge.rag.retriever.TfidfFallbackRetriever.retrieve_property_codes", return_value=["X-1"]
        ):
            r = LandsRagRetriever()
            out = r.retrieve_property_codes(RetrievalRequest(query="ویلا", top_k=1))
            self.assertEqual(out, ["X-1"])


if __name__ == "__main__":
    unittest.main()

