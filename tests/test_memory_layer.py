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

    def test_per_user_quota_10mb_default_and_trim(self) -> None:
        from app.memory.config import memory_max_bytes
        from app.memory.interfaces import MemoryItem
        from app.memory.store import FileMemoryStore, InMemoryMemoryStore

        self.assertEqual(memory_max_bytes(), 10 * 1024 * 1024)

        # سقف کوچک برای تست trim
        store = InMemoryMemoryStore(max_bytes=2500)
        self.assertEqual(store.max_bytes(), 2500)
        for i in range(40):
            store.upsert(
                MemoryItem(
                    id="",
                    user_key="09123334445",
                    memory_type="semantic",
                    key=f"note-{i}",
                    value=("یادداشت فروش فایل " + str(i) + " ") * 20,
                    score=0.5,
                )
            )
        used = store.usage_bytes("09123334445")
        self.assertLessEqual(used, 2500)
        self.assertGreater(used, 0)
        # کاربر دیگر سهم جدا دارد
        store.upsert(
            MemoryItem(
                id="",
                user_key="09125556667",
                memory_type="long_term",
                key="budget",
                value="بودجه ۱۰ میلیارد",
                score=0.9,
            )
        )
        self.assertGreater(len(store.list_items("09125556667")), 0)
        self.assertNotEqual(
            store.usage_bytes("09123334445"),
            0,
        )

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fstore = FileMemoryStore(root_dir=tmp, max_bytes=3000)
            for i in range(30):
                fstore.upsert(
                    MemoryItem(
                        id="",
                        user_key="09127778889",
                        memory_type="semantic",
                        key=f"k-{i}",
                        value=("حافظه اختصاصی " * 15) + str(i),
                        score=0.4,
                    )
                )
            self.assertLessEqual(fstore.usage_bytes("09127778889"), 3000)
            self.assertGreater(fstore.usage_bytes("09127778889"), 0)


if __name__ == "__main__":
    unittest.main()
