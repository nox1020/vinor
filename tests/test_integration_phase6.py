# -*- coding: utf-8 -*-
"""Phase 6 Integration — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class IntegrationFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_INTEGRATION")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.integration import config as cfg

            self.assertTrue(cfg.integration_enabled())
            self.assertTrue(cfg.integration_ui_enabled())
            self.assertTrue(cfg.integration_journey_enabled())
            self.assertTrue(cfg.integration_workflows_enabled())
            self.assertTrue(cfg.integration_ai_tools_enabled())
            self.assertTrue(cfg.integration_activity_hook_enabled())


class JourneyTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "INSTANCE_PATH": self.tmp,
            "VINOR_INTEGRATION_ENABLED": "1",
            "VINOR_INTEGRATION_JOURNEY_ENABLED": "1",
            "VINOR_CRM_ENABLED": "1",
            "VINOR_CRM_ACTIVITY_HOOK_ENABLED": "0",
            "VINOR_COMMERCIAL_ENABLED": "1",
            "VINOR_COMMERCIAL_ACTIVITY_HOOK_ENABLED": "0",
            "VINOR_CLOSING_ENABLED": "1",
            "VINOR_CLOSING_ACTIVITY_HOOK_ENABLED": "0",
            "VINOR_FOUNDATION_ENABLED": "0",
        }

    def test_journey_includes_crm_commercial_closing(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.crm.service import create_lead, upsert_contact
            from app.commercial.service import propose_offer
            from app.closing.service import upsert_deal
            from app.integration.service import get_journey_timeline

            lead = create_lead(
                partner_phone="09121111111",
                customer_phone="09123333333",
                display_name="لید تست",
            )
            self.assertIsNotNone(lead)
            contact = upsert_contact(
                partner_phone="09121111111",
                customer_phone="09123333333",
                display_name="لید تست",
                source="lead",
            )
            self.assertIsNotNone(contact)
            offer = propose_offer(
                partner_phone="09121111111",
                land_code="L601",
                amount=1_000_000,
                buyer_phone="09123333333",
            )
            self.assertIsNotNone(offer)
            deal = upsert_deal(
                partner_phone="09121111111",
                land_code="L601",
                status="open",
            )
            self.assertIsNotNone(deal)

            events = get_journey_timeline(partner_phone="09121111111", land_code="L601")
            stages = {e.stage for e in events}
            self.assertIn("lead", stages)
            self.assertIn("contact", stages)
            self.assertIn("negotiation", stages)
            self.assertIn("offer", stages)
            self.assertIn("deal", stages)

    def test_journey_empty_when_flag_off(self) -> None:
        env = {**self._env, "VINOR_INTEGRATION_JOURNEY_ENABLED": "0"}
        with mock.patch.dict(os.environ, env, clear=False):
            from app.integration.service import get_journey_timeline

            self.assertEqual(get_journey_timeline(partner_phone="09121111111"), [])


class IntegrationWorkflowFlagTests(unittest.TestCase):
    def test_intents_noop_when_workflows_off(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_INTEGRATION_ENABLED": "1",
                "VINOR_INTEGRATION_WORKFLOWS_ENABLED": "0",
            },
            clear=False,
        ):
            from app.conversation.interfaces import (
                INTENT_CONTRACT,
                INTENT_FOLLOWUP,
                INTENT_VISIT_RESULT,
            )
            from app.workflow.interfaces import WF_NONE
            from app.workflow.registry import WorkflowRegistry

            reg = WorkflowRegistry()
            self.assertEqual(reg.resolve_id(INTENT_VISIT_RESULT), WF_NONE)
            self.assertEqual(reg.resolve_id(INTENT_FOLLOWUP), WF_NONE)
            self.assertEqual(reg.resolve_id(INTENT_CONTRACT), WF_NONE)

    def test_intents_resolve_when_workflows_on(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_INTEGRATION_ENABLED": "1",
                "VINOR_INTEGRATION_WORKFLOWS_ENABLED": "1",
            },
            clear=False,
        ):
            from app.conversation.interfaces import (
                INTENT_CONTRACT,
                INTENT_FOLLOWUP,
                INTENT_VISIT_RESULT,
            )
            from app.workflow.registry import WorkflowRegistry

            reg = WorkflowRegistry()
            self.assertEqual(reg.resolve_id(INTENT_VISIT_RESULT), "visit_result")
            self.assertEqual(reg.resolve_id(INTENT_FOLLOWUP), "crm_followup")
            self.assertEqual(reg.resolve_id(INTENT_CONTRACT), "closing_contract")


class IntegrationAiToolsFlagTests(unittest.TestCase):
    def test_tools_absent_when_off(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_INTEGRATION_ENABLED": "0",
                "VINOR_INTEGRATION_AI_TOOLS_ENABLED": "0",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_deal", names)
            self.assertNotIn("propose_lead", names)
            self.assertNotIn("propose_task", names)

    def test_tools_present_when_on(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_INTEGRATION_ENABLED": "1",
                "VINOR_INTEGRATION_AI_TOOLS_ENABLED": "1",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_lead", names)
            self.assertIn("propose_task", names)
            self.assertIn("propose_deal", names)


class DealPathUntouchedTests(unittest.TestCase):
    def test_propose_deal_still_in_schema(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PARTNER

        names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
        self.assertIn("propose_deal", names)
        self.assertIn("propose_release_deal", names)


class RolesActivityHookTests(unittest.TestCase):
    def test_assign_roles_fail_open(self) -> None:
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(
            os.environ,
            {
                "INSTANCE_PATH": tmp,
                "VINOR_ROLES_ENABLED": "1",
                "VINOR_ROLES_ACTIVITY_HOOK_ENABLED": "1",
                "VINOR_FOUNDATION_ENABLED": "0",
            },
            clear=False,
        ):
            from app.roles.service import assign_roles

            a = assign_roles("09125555555", ["seller"], notes="phase6")
            self.assertIsNotNone(a)
            assert a is not None
            self.assertIn("seller", a.roles)


if __name__ == "__main__":
    unittest.main()
