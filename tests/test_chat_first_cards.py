# -*- coding: utf-8 -*-
"""Chat-First: living cards, message types, case timeline."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class CardRegistryTests(unittest.TestCase):
    def test_normalize_adds_id_version_history(self) -> None:
        from app.ai.card_registry import normalize_card

        card = normalize_card(
            {"type": "confirm_visit", "token": "abc", "title": "تأیید", "status": "pending"}
        )
        self.assertTrue(card.get("card_id"))
        self.assertEqual(card.get("state"), "pending")
        self.assertEqual(card.get("schema_version"), 1)
        self.assertEqual(card.get("version"), 1)
        self.assertTrue(card.get("history"))

    def test_transition_completed_bumps_version(self) -> None:
        from app.ai.card_registry import STATE_COMPLETED, apply_card_transition, normalize_card

        card = normalize_card({"type": "confirm_deal", "token": "t1", "status": "pending"})
        out = apply_card_transition(
            card,
            STATE_COMPLETED,
            event="card_confirmed",
            note="انجام شد",
            lines=["فایل: X", "شماره پیگیری: 1"],
            result={"visit_id": "1"},
        )
        self.assertEqual(out["state"], STATE_COMPLETED)
        self.assertEqual(out["status"], STATE_COMPLETED)
        self.assertGreaterEqual(int(out["version"]), 2)
        self.assertFalse(out.get("token_active", True))
        self.assertIn("انجام شد", out.get("note") or "")


class ChatStoreCardUpdateTests(unittest.TestCase):
    def test_update_agent_action_by_token(self) -> None:
        from app.ai import chat_store
        from app.ai.card_registry import STATE_COMPLETED

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            with mock.patch("app.ai.chat_store.ai_data_file", side_effect=lambda *p: str(data_root.joinpath(*p))), mock.patch(
                "app.ai.paths.ai_data_file", side_effect=lambda *p: str(data_root.joinpath(*p))
            ):
                # Ensure chats dir via append
                msgs, tid = chat_store.append_exchange(
                    "09121111111",
                    "ثبت بازدید",
                    "تأیید کنید",
                    audience="partner",
                    assistant_agent_actions=[
                        {
                            "type": "confirm_visit",
                            "token": "tok123",
                            "title": "تأیید",
                            "lines": ["فایل: A"],
                            "status": "pending",
                        }
                    ],
                )
                self.assertTrue(tid)
                self.assertTrue(msgs)
                ok, ui_msgs, out_tid = chat_store.update_agent_action_by_token(
                    "09121111111",
                    "tok123",
                    thread_id=tid,
                    audience="partner",
                    new_state=STATE_COMPLETED,
                    event="card_confirmed",
                    note="بازدید ثبت شد",
                    lines=["بازدید ثبت شد", "شماره پیگیری: V1"],
                    result={"visit_id": "V1"},
                )
                self.assertTrue(ok)
                self.assertEqual(out_tid, tid)
                # Find updated action
                found = False
                for m in ui_msgs:
                    for a in m.get("agent_actions") or []:
                        if a.get("token") == "tok123":
                            self.assertEqual(a.get("state"), STATE_COMPLETED)
                            found = True
                self.assertTrue(found)
                # cards_html should reflect done state
                html_blob = " ".join(str(m.get("cards_html") or "") for m in ui_msgs)
                self.assertIn("ai-agent-card--done", html_blob)


class MessageTypesTests(unittest.TestCase):
    def test_normalize_admin_source(self) -> None:
        from app.ai.message_types import MSG_ADMIN, normalize_message_type

        self.assertEqual(
            normalize_message_type(None, role="assistant", source="admin_escalation"),
            MSG_ADMIN,
        )


if __name__ == "__main__":
    unittest.main()
