# -*- coding: utf-8 -*-
"""نام مشتری فقط بعد از شروع عمدی فرم بازدید پرسیده شود."""
from __future__ import annotations

import unittest
from unittest import mock


class VisitAskNameGateTests(unittest.TestCase):
    def test_no_ask_name_without_awaiting_draft(self) -> None:
        from app.ai.agent_tools import VISIT_ASK_NAME, try_continue_visit_from_user_message

        with mock.patch(
            "app.ai.agent_tools._load_visit_draft",
            return_value={},
        ), mock.patch(
            "app.ai.agent_tools.resolve_conversation_land_code",
            return_value="1234567890",
        ) as resolve:
            out = try_continue_visit_from_user_message(
                "09121111111",
                "سلام باغ می‌خوام",
                audience="partner",
                voice="partner",
            )
        self.assertIsNone(out)
        resolve.assert_not_called()

    def test_orphan_land_only_draft_cleared(self) -> None:
        from app.ai.agent_tools import try_continue_visit_from_user_message

        with mock.patch(
            "app.ai.agent_tools._load_visit_draft",
            return_value={"land_code": "1234567890"},
        ), mock.patch(
            "app.ai.agent_tools.clear_visit_draft"
        ) as clear:
            out = try_continue_visit_from_user_message(
                "09121111111",
                "سلام",
                audience="partner",
                voice="partner",
            )
        self.assertIsNone(out)
        clear.assert_called_once_with("09121111111")

    def test_awaiting_name_asks_customer_name(self) -> None:
        from app.ai.agent_tools import VISIT_ASK_NAME, try_continue_visit_from_user_message

        with mock.patch(
            "app.ai.agent_tools._load_visit_draft",
            return_value={"land_code": "1234567890", "awaiting": "name"},
        ), mock.patch(
            "app.ai.agent_tools._looks_like_customer_name",
            return_value=False,
        ):
            out = try_continue_visit_from_user_message(
                "09121111111",
                "کار بعدی چیه",
                audience="partner",
                voice="partner",
            )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.get("reply"), VISIT_ASK_NAME)
        self.assertEqual((out.get("meta") or {}).get("provider"), "visit_step")

    def test_reset_visit_does_not_seed_orphan_draft(self) -> None:
        from app.ai.agent_tools import reset_visit_draft_keep_land

        with mock.patch(
            "app.ai.agent_tools.resolve_conversation_land_code",
            return_value="999",
        ), mock.patch(
            "app.ai.agent_tools._clear_visit_draft"
        ) as clear, mock.patch(
            "app.ai.agent_tools._save_visit_draft"
        ) as save:
            focus = reset_visit_draft_keep_land("09121111111", thread_id="t1")
        self.assertEqual(focus, "999")
        clear.assert_called_once()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
