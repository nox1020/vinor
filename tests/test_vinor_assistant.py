# -*- coding: utf-8 -*-
"""VinorAssistant — orchestrator, registry, intents and adapter tests."""
from __future__ import annotations

import unittest
from unittest import mock

_OK_MODEL_REPLY = {
    "ok": True,
    "reply": "چند فایل مناسب گرمابسرد دارم؛ کدام محدوده بودجه‌تان است؟",
    "meta": {"provider": "deepseek", "model": "test"},
}


def _app():
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


class VinorAssistantHandleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()

    def test_handle_returns_structured_reply(self) -> None:
        from app.ai.assistant import VinorAssistant

        cfg = {
            "enabled": True,
            "api_key_set": True,
            "model": "test",
            "spend_fuse": {"tripped": False},
        }
        with self.app.test_request_context("/ai/chat"):
            with mock.patch("app.ai.provider.call_model", return_value=dict(_OK_MODEL_REPLY)), \
                 mock.patch("app.ai.services.ai_config", return_value=cfg), \
                 mock.patch("app.ai.assistant.apply_credit_guard", return_value=None):
                out = VinorAssistant().handle(
                    "زمین گرمابسرد دارید؟",
                    user_key="09121234567",
                    audience="partner",
                    thread_id="t-test",
                )
        self.assertIsInstance(out, dict)
        self.assertIn("ok", out)
        self.assertTrue(out.get("ok"), msg=out.get("error"))
        self.assertIn("reply", out)
        self.assertTrue(str(out.get("reply") or "").strip())

    def test_handle_rejects_empty_message(self) -> None:
        from app.ai.assistant import VinorAssistant

        with self.app.test_request_context("/ai/chat"):
            out = VinorAssistant().handle("   ", user_key="09121234567", audience="partner")
        self.assertFalse(out.get("ok"))

    def test_generate_reply_is_an_adapter(self) -> None:
        from app.ai.services import generate_reply

        with self.app.test_request_context("/ai/chat"):
            with mock.patch(
                "app.ai.assistant.VinorAssistant.handle",
                return_value={"ok": True, "reply": "سلام"},
            ) as handle:
                out = generate_reply(
                    "سلام",
                    user_key="09121234567",
                    audience="partner",
                    thread_id="t-adapter",
                )
        self.assertEqual(out, {"ok": True, "reply": "سلام"})
        self.assertEqual(handle.call_count, 1)
        kwargs = handle.call_args.kwargs
        self.assertEqual(kwargs.get("audience"), "partner")
        self.assertEqual(kwargs.get("thread_id"), "t-adapter")


class ToolRegistryTests(unittest.TestCase):
    def test_registry_lists_core_tools(self) -> None:
        from app.ai.tools import registry

        names = {spec.name for spec in registry.list_tools()}
        for tool in (
            "search_lands",
            "propose_visit_request",
            "propose_lead",
            "propose_deal",
            "admin_ops_summary",
        ):
            self.assertIn(tool, names)

    def test_public_cannot_run_propose_visit(self) -> None:
        from app.ai.tools import registry

        self.assertFalse(registry.is_allowed("propose_visit_request", "public"))
        self.assertTrue(registry.is_allowed("propose_visit_request", "partner"))
        self.assertNotIn(
            "propose_visit_request", registry.tool_names_for_voice("public")
        )

    def test_run_tool_rechecks_permission(self) -> None:
        """لایهٔ دوم مجوز — رجیستری اجرا را به run_tool می‌دهد و آن رد می‌کند."""
        app = _app()
        with app.test_request_context("/ai/chat"):
            from app.ai.tools import registry

            out = registry.execute(
                "propose_visit_request",
                {"land_code": "V-1"},
                phone="09121234567",
                audience="public",
                voice="public",
            )
        self.assertFalse(out.get("ok"))

    def test_lawyer_voice_has_no_tools(self) -> None:
        from app.ai.tools import registry

        self.assertEqual(registry.tool_names_for_voice("lawyer"), [])

    def test_propose_tools_require_confirmation(self) -> None:
        from app.ai.tools import registry

        self.assertTrue(registry.requires_confirmation("propose_deal"))
        self.assertFalse(registry.requires_confirmation("search_lands"))


class IntentTests(unittest.TestCase):
    def test_partner_search_signals_include_zamin(self) -> None:
        from app.ai.intents import detect_intent, message_signals

        self.assertTrue(message_signals("زمین گرمابسرد")["search"])
        self.assertTrue(detect_intent("زمین گرمابسرد دارید؟").wants_search)

    def test_search_tool_selected_for_land_question(self) -> None:
        from app.ai.tools.selection import select_tool_names_for_request

        names = select_tool_names_for_request(
            "partner", user_message="زمین گرمابسرد چند؟"
        )
        self.assertIn("search_lands", names)

    def test_visit_result_selected_for_outcome_phrase(self) -> None:
        from app.ai.tools.selection import select_tool_names_for_request

        names = select_tool_names_for_request(
            "partner", user_message="مشتری علاقه‌مند بود"
        )
        self.assertIn("propose_visit_result", names)

    def test_pipeline_peygiri_selects_next_action_not_crm(self) -> None:
        from app.ai.tools.selection import select_tool_names_for_request

        names = select_tool_names_for_request("partner", user_message="پیگیری")
        self.assertIn("suggest_next_action", names)
        self.assertNotIn("propose_followup", names)
        self.assertNotIn("propose_log_call", names)

    def test_visit_result_chip_tools(self) -> None:
        from app.ai.tools.selection import select_tool_names_for_request

        names = select_tool_names_for_request(
            "partner", user_message="نتیجه بازدید را ثبت کن", chip_intent="visit_result"
        )
        self.assertIn("propose_visit_result", names)
        self.assertIn("propose_no_show", names)


if __name__ == "__main__":
    unittest.main()
