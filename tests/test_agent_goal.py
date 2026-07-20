# -*- coding: utf-8 -*-
"""قفل هدف ایجنت — schema فقط هسته فروش؛ بدون هویت مأموریت/چندایجنت."""
from __future__ import annotations

import json
import unittest
from unittest import mock


class AgentGoalLockTests(unittest.TestCase):
    def test_goal_system_in_all_prompts(self) -> None:
        from app.ai.config import prompt_for_voice
        from app.ai.goal import GOAL_SYSTEM

        for voice in ("public", "partner", "special"):
            prompt = prompt_for_voice(voice)
            self.assertIn(GOAL_SYSTEM, prompt)
            self.assertNotIn("مأموریت", prompt)
            self.assertNotIn("ماموریت", prompt)
            self.assertIn("یک نفر هستی", prompt)

    def test_agent_system_hint_two_paths(self) -> None:
        from app.ai.agent_tools import agent_system_hint
        from app.ai.goal import GOAL_SYSTEM

        pub = agent_system_hint("public")
        self.assertIn(GOAL_SYSTEM, pub)
        self.assertIn("خرید", pub)
        self.assertIn("بازاریاب", pub)
        self.assertNotIn("مأموریت", pub)

        partner = agent_system_hint("partner")
        self.assertIn(GOAL_SYSTEM, partner)
        self.assertIn("propose_visit", partner.lower() + "propose_visit")
        self.assertTrue("visit" in partner.lower() or "بازدید" in partner or "next_action" in partner)
        self.assertNotIn("مأموریت", partner)

    def test_public_schema_core_only(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PUBLIC
        from app.ai.goal import CORE_TOOLS_PUBLIC, EXTENDED_CHAT_TOOLS

        names = {t["function"]["name"] for t in tools_schema_for_voice(VOICE_PUBLIC)}
        self.assertEqual(names, set(CORE_TOOLS_PUBLIC))
        self.assertTrue(names.isdisjoint(EXTENDED_CHAT_TOOLS))

    def test_partner_schema_excludes_extended(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PARTNER
        from app.ai.goal import CORE_TOOLS_PARTNER, EXTENDED_CHAT_TOOLS

        names = {t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)}
        self.assertTrue(names.isdisjoint(EXTENDED_CHAT_TOOLS))
        self.assertTrue({"search_lands", "propose_deal", "propose_visit_request"} <= names)
        self.assertTrue(names <= CORE_TOOLS_PARTNER)

    def test_schema_descriptions_have_no_mission_copy(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PARTNER, VOICE_PUBLIC

        for voice in (VOICE_PUBLIC, VOICE_PARTNER):
            blob = json.dumps(tools_schema_for_voice(voice), ensure_ascii=False)
            self.assertNotIn("مأموریت", blob)
            self.assertNotIn("ماموریت", blob)

    def test_hint_wrap_keeps_single_identity(self) -> None:
        from app.ai.goal import GOAL_HINT_PREFIX, wrap_internal_hint

        w = wrap_internal_hint("پیشنهاد فایل X")
        self.assertTrue(w.startswith(GOAL_HINT_PREFIX))
        self.assertEqual(wrap_internal_hint(w), w)

    def test_single_marketer_chat_default_on(self) -> None:
        from app.ai.goal import single_marketer_chat_enabled

        self.assertTrue(single_marketer_chat_enabled())

    def test_partner_chat_skips_workflow(self) -> None:
        from app.conversation.di import make_conversation_manager
        from app.conversation.interfaces import ROLE_PARTNER, IdentityInfo

        phone = "09121111111"
        mgr = make_conversation_manager()
        identity = IdentityInfo(
            role=ROLE_PARTNER,
            user_key=phone,
            phone=phone,
            is_logged_in=True,
            is_partner=True,
        )
        with mock.patch.object(mgr._identity, "resolve", return_value=identity):
            out = mgr.handle(
                message="ثبت بازدید",
                user_key=phone,
                audience="partner",
                chip_intent="visit",
            )
        self.assertFalse(out.handled)
        self.assertTrue(out.pass_to_supervisor)
        self.assertEqual(
            (out.observability or {}).get("skip_reason"),
            "partner_chat_tools_only",
        )


if __name__ == "__main__":
    unittest.main()
