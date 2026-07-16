from __future__ import annotations

import unittest
from unittest.mock import patch

from app.ai.context import _select_lands_for_query


class ContextRagBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lands = [
            {"code": "V-1", "title": "ویلا دماوند", "city": "دماوند", "location": "گرمابسرد"},
            {"code": "Z-2", "title": "زمین تهران", "city": "تهران", "location": "لواسان"},
        ]

    def test_rag_selection_used_when_available(self) -> None:
        with patch("app.ai.context._select_lands_by_rag", return_value=[self.lands[1], self.lands[0]]):
            out = _select_lands_for_query(self.lands, "بین این دو فایل مقایسه کن", default_limit=2, match_limit=2)
            self.assertEqual([x["code"] for x in out], ["Z-2", "V-1"])

    def test_fallback_to_heuristic_when_rag_empty(self) -> None:
        with patch("app.ai.context._select_lands_by_rag", return_value=[]):
            out = _select_lands_for_query(self.lands, "ویلا در دماوند", default_limit=2, match_limit=2)
            self.assertEqual(out[0]["code"], "V-1")


if __name__ == "__main__":
    unittest.main()

