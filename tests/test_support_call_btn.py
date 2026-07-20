# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest


class SupportCallBtnTests(unittest.TestCase):
    def test_public_lands_get_call_btn(self) -> None:
        from app.ai.agent_tools import append_support_call_if_needed, support_call_phone

        html = append_support_call_if_needed(
            '<div class="ai-land-cards"></div>',
            "این فایل مناسبه.",
            land_codes=["123"],
            audience="public",
        )
        self.assertIn("ai-agent-btn--call", html)
        self.assertIn(f"tel:{support_call_phone()}", html)
        self.assertIn("پشتیبانی", html)

    def test_no_duplicate_call_btn(self) -> None:
        from app.ai.agent_tools import append_support_call_if_needed

        existing = '<a class="ai-agent-btn ai-agent-btn--call" href="tel:09121471301">x</a>'
        html = append_support_call_if_needed(
            existing,
            "با پشتیبانی تماس بگیر",
            audience="partner",
        )
        self.assertEqual(html.count("ai-agent-btn--call"), 1)

    def test_reply_mention_adds_call(self) -> None:
        from app.ai.agent_tools import append_support_call_if_needed

        html = append_support_call_if_needed(
            "",
            "برای هماهنگی بازدید با پشتیبانی تماس بگیر.",
            audience="partner",
        )
        self.assertIn("ai-agent-btn--call", html)

    def test_plain_hello_no_call(self) -> None:
        from app.ai.agent_tools import append_support_call_if_needed

        html = append_support_call_if_needed(
            "",
            "سلام، چطور کمک کنم؟",
            audience="partner",
        )
        self.assertEqual(html, "")


if __name__ == "__main__":
    unittest.main()
