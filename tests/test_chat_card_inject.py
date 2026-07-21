# -*- coding: utf-8 -*-
"""Chat injection: land + action cards land in the conversation thread."""
from __future__ import annotations

import unittest
from unittest import mock


class ChatCardInjectTests(unittest.TestCase):
    def test_enrich_merges_land_into_cards_html(self) -> None:
        from app.ai import chat_store

        messages = [
            {
                "role": "assistant",
                "content": "این فایل‌ها",
                "land_codes": ["1001"],
                "agent_actions": [],
                "created_at": "2026-07-18T10:00:00Z",
            }
        ]
        fake_payload = [{"code": "1001", "html": '<div class="ai-land-cards__slot">card</div>'}]
        fake_land_html = (
            '<div class="ai-land-cards" role="list">'
            '<div class="ai-land-cards__slot">card</div></div>'
        )
        with mock.patch(
            "app.ai.land_cards.land_cards_payload", return_value=fake_payload
        ), mock.patch(
            "app.ai.land_cards.render_land_cards_html", return_value=fake_land_html
        ), mock.patch(
            "app.ai.agent_tools.render_agent_actions_html", return_value=""
        ):
            out = chat_store._enrich_messages_for_ui("09121111111", messages, "partner")
        self.assertEqual(len(out), 1)
        self.assertIn("ai-land-cards", out[0].get("cards_html") or "")
        self.assertTrue(out[0].get("land_cards"))

    def test_enrich_merges_actions_after_lands(self) -> None:
        from app.ai import chat_store

        messages = [
            {
                "role": "assistant",
                "content": "تأیید کنید",
                "land_codes": ["1001"],
                "agent_actions": [{"type": "confirm_visit", "token": "t"}],
                "created_at": "2026-07-18T10:00:00Z",
            }
        ]
        with mock.patch(
            "app.ai.land_cards.land_cards_payload",
            return_value=[{"code": "1001", "html": "<div>x</div>"}],
        ), mock.patch(
            "app.ai.land_cards.render_land_cards_html",
            return_value='<div class="ai-land-cards">L</div>',
        ), mock.patch(
            "app.ai.agent_tools.render_agent_actions_html",
            return_value='<div class="ai-agent-card">A</div>',
        ):
            out = chat_store._enrich_messages_for_ui("09121111111", messages, "partner")
        html = out[0].get("cards_html") or ""
        self.assertIn("ai-land-cards", html)
        self.assertIn("ai-agent-card", html)
        self.assertLess(html.index("ai-land-cards"), html.index("ai-agent-card"))

    def test_enrich_keeps_action_cards_when_land_render_fails(self) -> None:
        from app.ai import chat_store

        messages = [
            {
                "role": "assistant",
                "content": "تأیید کنید",
                "land_codes": ["1001"],
                "meta": {"show_land_cards": True},
                "agent_actions": [{"type": "confirm_broadcast_sms", "token": "t"}],
            }
        ]
        with mock.patch(
            "app.ai.land_cards.land_cards_payload",
            side_effect=RuntimeError("land boom"),
        ), mock.patch(
            "app.ai.agent_tools.render_agent_actions_html",
            return_value='<div class="ai-agent-card">A</div>',
        ):
            out = chat_store._enrich_messages_for_ui("admin_test", messages, "admin")
        html = out[0].get("cards_html") or ""
        self.assertIn("ai-agent-card", html)

    def test_enrich_admin_action_only(self) -> None:
        from app.ai import chat_store

        messages = [
            {
                "role": "assistant",
                "content": "کارت",
                "agent_actions": [{"type": "confirm_partner_decision", "token": "t"}],
            }
        ]
        with mock.patch(
            "app.ai.agent_tools.render_agent_actions_html",
            return_value='<div class="ai-agent-card">P</div>',
        ):
            out = chat_store._enrich_messages_for_ui("admin_test", messages, "admin")
        self.assertIn("ai-agent-card", out[0].get("cards_html") or "")


if __name__ == "__main__":
    unittest.main()
