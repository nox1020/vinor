from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class VinorOpensChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = self._tmpdir.name

        def _ai_file(*parts: str) -> str:
            return os.path.join(root, *parts)

        # chat_store binds ai_data_file at import time. Patch that name too so a
        # full-suite run does not read or write the real instance chat files.
        for target in ("app.ai.paths.ai_data_file", "app.ai.chat_store.ai_data_file"):
            patcher = mock.patch(target, side_effect=_ai_file)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_empty_thread_gets_vinor_opening(self) -> None:
        from app.ai.audience import AUDIENCE_PUBLIC
        from app.ai.chat_store import ensure_active_thread, messages_for_ui
        from app.ai.welcome import ensure_vinor_opens_chat, is_welcome_message, opening_text

        key = "guest_test_open"
        tid = ensure_active_thread(key, audience=AUDIENCE_PUBLIC)
        seeded = messages_for_ui(key, tid, audience=AUDIENCE_PUBLIC)
        # گفتگوی تازه یا خالی است یا فقط پیام خوش‌آمد وینور را دارد
        self.assertTrue(all(is_welcome_message(m) for m in seeded))

        msgs, out_tid = ensure_vinor_opens_chat(
            key,
            audience=AUDIENCE_PUBLIC,
            thread_id=tid,
            text=opening_text(),
        )
        self.assertEqual(out_tid, tid)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "assistant")
        self.assertTrue(is_welcome_message(msgs[0]))
        self.assertEqual(msgs[0]["content"].strip(), opening_text().strip())

        # دوباره صدا زدن پیام تکراری نسازد
        msgs2, _ = ensure_vinor_opens_chat(
            key,
            audience=AUDIENCE_PUBLIC,
            thread_id=tid,
            text=opening_text(),
        )
        self.assertEqual(len(msgs2), 1)

    def test_clear_reseeds_opening(self) -> None:
        from app.ai.audience import AUDIENCE_PUBLIC
        from app.ai.chat_store import append_exchange, clear_chat, ensure_active_thread
        from app.ai.welcome import is_welcome_message, opening_text

        key = "guest_test_clear"
        tid = ensure_active_thread(key, audience=AUDIENCE_PUBLIC)
        append_exchange(
            key,
            "سلام",
            "سلام!",
            thread_id=tid,
            audience=AUDIENCE_PUBLIC,
        )
        out = clear_chat(key, audience=AUDIENCE_PUBLIC, opening_text=opening_text())
        self.assertTrue(out.get("ok"))
        msgs = out.get("messages") or []
        self.assertEqual(len(msgs), 1)
        self.assertTrue(is_welcome_message(msgs[0]))


if __name__ == "__main__":
    unittest.main()
