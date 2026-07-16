from __future__ import annotations

import tempfile
import unittest

from app.knowledge.rag.models import LandDocument
from app.knowledge.rag.vector_store import LandsVectorStore


class LandsVectorStoreTests(unittest.TestCase):
    def test_query_returns_relevant_code_with_filter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = LandsVectorStore(index_path=f"{td}/lands_index.json")
            store.build(
                [
                    LandDocument(
                        code="A-101",
                        text="ویلا لوکس دماوند گرمابسرد 12 میلیارد",
                        city="دماوند",
                        location="گرمابسرد",
                        category="ویلا",
                        status="active",
                        tags=["لوکس"],
                        price_total=12_000_000_000,
                        area_total=320,
                    ),
                    LandDocument(
                        code="B-201",
                        text="زمین سرمایه گذاری تهران 30 میلیارد",
                        city="تهران",
                        location="لواسان",
                        category="زمین",
                        status="active",
                        tags=["سرمایه گذاری"],
                        price_total=30_000_000_000,
                        area_total=900,
                    ),
                ],
                source_mtime=1.0,
            )
            out = store.query(
                "ویلا تا 15 میلیارد در دماوند",
                top_k=3,
                metadata_filter={"city": "دماوند", "category": "ویلا", "max_price": 15_000_000_000},
            )
            self.assertEqual(out, ["A-101"])


if __name__ == "__main__":
    unittest.main()

