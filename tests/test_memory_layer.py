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

    def test_sales_event_and_like_reject_conflict(self) -> None:
        from app.memory.events import record_sales_event
        from app.memory.store import InMemoryMemoryStore
        from unittest import mock

        store = InMemoryMemoryStore()
        with mock.patch("app.memory.di.make_memory_store", return_value=store):
            with mock.patch("app.memory.config.memory_enabled", return_value=True):
                record_sales_event("09121111111", "liked", land_code="A-1")
                record_sales_event("09121111111", "rejected", land_code="A-1")
        keys = {it.key for it in store.list_items("09121111111")}
        self.assertIn("rejected:A-1", keys)
        self.assertNotIn("liked:A-1", keys)

    def test_short_term_ttl_and_budget_conflict(self) -> None:
        from datetime import datetime, timedelta, timezone
        from app.memory.interfaces import MEMORY_LONG, MEMORY_SHORT, MemoryItem
        from app.memory.lifecycle import conflicting_ids, is_expired, resolve_conflicts
        from app.memory.store import InMemoryMemoryStore

        old = MemoryItem(
            id="s1",
            user_key="09121111111",
            memory_type=MEMORY_SHORT,
            key="last_user_intent",
            value="قدیمی",
            score=0.5,
            created_at=(datetime.now(timezone.utc) - timedelta(hours=100)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            updated_at=(datetime.now(timezone.utc) - timedelta(hours=100)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        )
        self.assertTrue(is_expired(old))

        store = InMemoryMemoryStore()
        store.upsert(
            MemoryItem(
                id="",
                user_key="09121111111",
                memory_type=MEMORY_LONG,
                key="budget",
                value="بودجه ۱۰ میلیارد",
                score=0.9,
            )
        )
        store.upsert(
            MemoryItem(
                id="",
                user_key="09121111111",
                memory_type=MEMORY_LONG,
                key="city:دماوند",
                value="علاقه به دماوند",
                score=0.9,
            )
        )
        incoming = MemoryItem(
            id="",
            user_key="09121111111",
            memory_type=MEMORY_LONG,
            key="city:گرمابسرد",
            value="علاقه به گرمابسرد",
            score=0.95,
        )
        self.assertTrue(conflicting_ids(store.list_items("09121111111"), incoming))
        resolve_conflicts(store, incoming)
        store.upsert(incoming)
        cities = [it.key for it in store.list_items("09121111111") if str(it.key).startswith("city:")]
        self.assertEqual(cities, ["city:گرمابسرد"])

    def test_guest_memory_merge(self) -> None:
        from app.memory.interfaces import MEMORY_LONG, MemoryItem
        from app.memory.merge import merge_user_memory
        from app.memory.store import InMemoryMemoryStore

        store = InMemoryMemoryStore()
        store.upsert(
            MemoryItem(
                id="",
                user_key="guest_abc123",
                memory_type=MEMORY_LONG,
                key="budget",
                value="بودجه ۱۵ میلیارد",
                score=0.9,
            )
        )
        out = merge_user_memory("guest_abc123", "09121111111", store=store)
        self.assertGreaterEqual(out["merged"], 1)
        vals = [it.value for it in store.list_items("09121111111")]
        self.assertTrue(any("۱۵" in v or "15" in v for v in vals))

    def test_stage_aware_retrieve_boosts_relationship(self) -> None:
        from app.memory.interfaces import MEMORY_LONG, MEMORY_RELATIONSHIP, MemoryItem, MemoryRetrieveRequest
        from app.memory.retriever import DynamicMemoryRetriever
        from app.memory.store import InMemoryMemoryStore
        from app.memory.summarizer import CompactMemorySummarizer

        store = InMemoryMemoryStore()
        store.upsert(
            MemoryItem(
                id="",
                user_key="09121111111",
                memory_type=MEMORY_LONG,
                key="pref:لوکس",
                value="ترجیح لوکس",
                score=0.5,
            )
        )
        store.upsert(
            MemoryItem(
                id="",
                user_key="09121111111",
                memory_type=MEMORY_RELATIONSHIP,
                key="visit:V-9",
                value="بازدید ثبت شد: V-9",
                score=0.5,
                metadata={"source": "sales_event", "land_code": "V-9"},
            )
        )
        ret = DynamicMemoryRetriever(store, CompactMemorySummarizer())
        out = ret.retrieve(
            MemoryRetrieveRequest(
                user_key="09121111111",
                query="",
                stage="visit",
                top_k=2,
                budget_chars=200,
            )
        )
        self.assertTrue(out.items)
        self.assertEqual(out.items[0].key, "visit:V-9")


if __name__ == "__main__":
    unittest.main()
