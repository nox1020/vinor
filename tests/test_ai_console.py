# -*- coding: utf-8 -*-
"""AI Mission Control — unit tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock


class AiConsoleFlagsTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_AI_CONSOLE")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.ai_console import config as cfg

            self.assertTrue(cfg.ai_console_enabled())
            self.assertTrue(cfg.ai_console_ui_enabled())
            self.assertTrue(cfg.ai_console_mutate_enabled())


class AiConsoleCatalogTests(unittest.TestCase):
    def test_tools_and_agents_nonempty(self) -> None:
        from app.ai_console import catalog

        tools = catalog.list_tools()
        names = [t["name"] for t in tools]
        self.assertIn("propose_deal", names)
        self.assertIn("propose_lead", names)
        agents = catalog.list_agents()
        ids = [a["id"] for a in agents]
        self.assertIn("property_search", ids)
        self.assertTrue(catalog.list_workflow_definitions())
        self.assertTrue(catalog.list_ai_flags())


class AiConsoleReadersTests(unittest.TestCase):
    def test_conversation_index_and_pending(self) -> None:
        tmp = tempfile.mkdtemp()
        chats = os.path.join(tmp, "ai_chats", "partner")
        os.makedirs(chats, exist_ok=True)
        with open(os.path.join(chats, "09121111111.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "user_key": "09121111111",
                    "threads": [
                        {
                            "id": "t1",
                            "title": "تست",
                            "updated_at": "2026-07-18T10:00:00Z",
                            "messages": [{"role": "user", "content": "سلام"}],
                        }
                    ],
                },
                f,
            )
        with mock.patch.dict(os.environ, {"INSTANCE_PATH": tmp}, clear=False):
            with mock.patch("app.ai.paths.ai_data_file", side_effect=lambda n: os.path.join(tmp, n)):
                from app.ai_console import readers

                rows = readers.list_conversation_index(limit=10)
                self.assertTrue(any(r.get("thread_id") == "t1" for r in rows))


class AiConsoleDashboardTests(unittest.TestCase):
    def test_dashboard_snapshot_keys(self) -> None:
        from app.ai_console.service import dashboard_snapshot

        snap = dashboard_snapshot()
        self.assertIn("kpis", snap)
        self.assertIn("agents", snap)
        self.assertIn("pending_confirms", snap["kpis"])


class AiConsoleRbacTests(unittest.TestCase):
    def test_ai_read_in_base_admin(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"VINOR_HARDENING_ENABLED": "1", "VINOR_HARDENING_RBAC_ENABLED": "1"},
            clear=False,
        ):
            from app.hardening.permissions import (
                PERM_AI_FLAGS,
                PERM_AI_READ,
                list_permissions,
            )

            sess = {"logged_in": True}
            with mock.patch("app.roles.service.is_super_admin", return_value=False):
                perms = list_permissions(session=sess)
                self.assertIn(PERM_AI_READ, perms)
                self.assertNotIn(PERM_AI_FLAGS, perms)


if __name__ == "__main__":
    unittest.main()
