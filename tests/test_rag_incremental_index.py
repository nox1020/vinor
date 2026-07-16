from __future__ import annotations

import unittest
from unittest.mock import patch

from app.knowledge.rag.models import LandDocument
from app.knowledge.rag.retriever import LandsRagRetriever


class _CountingProvider:
    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += len(texts)
        return [[1.0, 0.0] for _ in texts]


class _DummyStore:
    def __init__(self):
        self.rows = []

    def rebuild(self, rows):
        self.rows = rows

    def search(self, query_vector, *, top_k, allowed_ids=None, metadata_filter=None):
        return [r.id for r in self.rows[:top_k]]


class RagIncrementalIndexTests(unittest.TestCase):
    def test_no_reembed_for_unchanged_docs(self):
        provider = _CountingProvider()
        store = _DummyStore()
        docs = [
            LandDocument("A-1", "ویلا", "دماوند", "گرمابسرد", "ویلا", "active", [], 1, 1),
            LandDocument("B-2", "زمین", "دماوند", "گرمابسرد", "زمین", "active", [], 1, 1),
        ]
        with patch("app.knowledge.rag.retriever.make_embedding_provider", return_value=provider), patch(
            "app.knowledge.rag.retriever.make_vector_store", return_value=store
        ), patch("app.knowledge.rag.retriever.load_land_documents", return_value=docs), patch(
            "app.knowledge.rag.retriever.lands_source_mtime", side_effect=[2.0, 2.0, 2.0]
        ):
            r = LandsRagRetriever()
            r.ensure_index()
            first_calls = provider.calls
            r.ensure_index()
            second_calls = provider.calls
            self.assertEqual(first_calls, 2)
            self.assertEqual(second_calls, 2)


if __name__ == "__main__":
    unittest.main()

