from __future__ import annotations

import unittest

from app.memory.extractor import RuleMemoryExtractor
from app.memory.interfaces import MemoryExtractRequest, MemoryRetrieveRequest
from app.memory.manager import DefaultMemoryManager, DefaultMemoryProvider
from app.memory.retriever import DynamicMemoryRetriever
from app.memory.store import InMemoryMemoryStore
from app.memory.summarizer import CompactMemorySummarizer


class MemoryLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryMemoryStore()
        self.manager = DefaultMemoryManager(
            store=self.store,
            extractor=RuleMemoryExtractor(),
            retriever=DynamicMemoryRetriever(self.store, CompactMemorySummarizer()),
        )
        self.provider = DefaultMemoryProvider(self.manager)

    def test_extract_budget_and_city(self) -> None:
        saved = self.provider.learn_from_exchange(
            MemoryExtractRequest(
                user_key="09121111111",
                user_message="ویلا تا ۱۵ میلیارد در دماوند می‌خوام",
                assistant_reply="چند فایل مناسب پیدا کردم.",
                audience="public",
                land_codes=("V-10",),
            )
        )
        self.assertTrue(len(saved) >= 2)
        keys = {s.key for s in saved}
        self.assertTrue(any(k.startswith("budget") or k == "budget" for k in keys))
        self.assertTrue(any("viewed:V-10" == k for k in keys))

    def test_retrieve_respects_budget(self) -> None:
        self.provider.learn_from_exchange(
            MemoryExtractRequest(
                user_key="09121111111",
                user_message="ویلا لوکس در گرمابسرد با بودجه ۲۰ میلیارد",
                assistant_reply="باشه",
                land_codes=("A-1", "B-2"),
            )
        )
        out = self.provider.get_prompt_memory(
            MemoryRetrieveRequest(
                user_key="09121111111",
                query="ویلا در گرمابسرد",
                budget_chars=120,
                top_k=8,
            )
        )
        self.assertLessEqual(len(out.text), 140)
        self.assertIn("=== حافظه مرتبط کاربر ===", out.text)
        self.assertGreater(out.memory_tokens, 0)

    def test_noise_not_stored_as_semantic(self) -> None:
        saved = self.provider.learn_from_exchange(
            MemoryExtractRequest(
                user_key="09121111111",
                user_message="سلام",
                assistant_reply="سلام، چطور کمک کنم؟",
            )
        )
        # noise should not create semantic/long preference spam
        types = {s.memory_type for s in saved}
        self.assertNotIn("semantic", types)

    def test_delete_and_edit(self) -> None:
        saved = self.provider.learn_from_exchange(
            MemoryExtractRequest(
                user_key="09121111111",
                user_message="زمین برای سرمایه‌گذاری در دماوند",
                assistant_reply="باشه",
            )
        )
        self.assertTrue(saved)
        mid = saved[0].id
        edited = self.manager.edit_memory("09121111111", mid, value="ترجیح زمین سرمايه‌گذاری")
        self.assertIsNotNone(edited)
        self.assertEqual(edited.value, "ترجیح زمین سرمايه‌گذاری")
        self.assertTrue(self.manager.delete_memory("09121111111", mid))


if __name__ == "__main__":
    unittest.main()
