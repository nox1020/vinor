# -*- coding: utf-8 -*-
"""Phase 3 Commercial — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class CommercialFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_COMMERCIAL")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.commercial import config as cfg

            self.assertTrue(cfg.commercial_enabled())
            self.assertTrue(cfg.commercial_ui_enabled())
            self.assertTrue(cfg.commercial_buyer_ui_enabled())
            self.assertTrue(cfg.commercial_ai_tools_enabled())
            self.assertTrue(cfg.commercial_workflow_enabled())
            self.assertTrue(cfg.commercial_visit_bridge_enabled())


class CommercialCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_COMMERCIAL_ENABLED": "1",
            "VINOR_COMMERCIAL_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_offer_counter_reservation_flow(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.commercial.service import (
                hold_reservation,
                list_partner_offers,
                propose_counter,
                propose_offer,
                release_reservation,
                respond_offer,
            )

            offer = propose_offer(
                land_code="101",
                partner_phone="09121111111",
                buyer_phone="09122222222",
                amount=5_000_000_000,
                terms="نقد",
                proposed_by="partner",
            )
            self.assertIsNotNone(offer)
            assert offer is not None
            self.assertEqual(offer.status, "pending")
            self.assertEqual(len(list_partner_offers("09121111111")), 1)

            counter = propose_counter(
                offer_id=offer.id,
                amount=4_800_000_000,
                proposed_by="buyer",
            )
            self.assertIsNotNone(counter)
            from app.commercial.service import get_offer

            updated = get_offer(offer.id)
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.status, "countered")

            accepted = respond_offer(offer.id, action="accept", actor_key="09121111111")
            self.assertIsNotNone(accepted)
            assert accepted is not None
            self.assertEqual(accepted.status, "accepted")

            res = hold_reservation(offer_id=offer.id, actor_key="09121111111")
            self.assertIsNotNone(res)
            assert res is not None
            self.assertEqual(res.status, "held")
            # soft hold: no assignment mutation implied
            self.assertEqual(res.land_code, "101")

            released = release_reservation(res.id, actor_key="09121111111")
            self.assertIsNotNone(released)
            assert released is not None
            self.assertEqual(released.status, "released")


class CommercialVisitBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_COMMERCIAL_ENABLED": "1",
            "VINOR_COMMERCIAL_VISIT_BRIDGE_ENABLED": "1",
            "VINOR_COMMERCIAL_ACTIVITY_HOOK_ENABLED": "0",
            "VINOR_VISIT_RESULT_ENABLED": "1",
            "VINOR_VISIT_RESULT_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_interested_opens_negotiation(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.visit_result.service import register_result
            from app.commercial.service import list_partner_negotiations

            result = register_result(
                visit_request_id="vcom1",
                partner_phone="09123333333",
                land_code="202",
                outcome="interested",
            )
            self.assertIsNotNone(result)
            negs = list_partner_negotiations("09123333333")
            self.assertGreaterEqual(len(negs), 1)
            self.assertEqual(negs[0].land_code, "202")
            self.assertEqual(negs[0].source, "visit")

    def test_bridge_off_no_negotiation(self) -> None:
        env = {**self._env, "VINOR_COMMERCIAL_VISIT_BRIDGE_ENABLED": "0"}
        with mock.patch.dict(os.environ, env, clear=False):
            from app.visit_result.service import register_result
            from app.commercial.service import list_partner_negotiations

            register_result(
                visit_request_id="vcom2",
                partner_phone="09124444444",
                land_code="303",
                outcome="interested",
            )
            self.assertEqual(list_partner_negotiations("09124444444"), [])


class CommercialAiToolsFlagTests(unittest.TestCase):
    def test_tools_absent_when_off(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_COMMERCIAL_ENABLED": "0",
                "VINOR_COMMERCIAL_AI_TOOLS_ENABLED": "0",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_deal", names)
            self.assertNotIn("propose_offer", names)
            self.assertNotIn("propose_counter_offer", names)
            self.assertNotIn("propose_reservation", names)

    def test_tools_present_when_on(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_COMMERCIAL_ENABLED": "1",
                "VINOR_COMMERCIAL_AI_TOOLS_ENABLED": "1",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_offer", names)
            self.assertIn("propose_counter_offer", names)
            self.assertIn("propose_reservation", names)
            self.assertIn("propose_deal", names)


class CommercialWorkflowFlagTests(unittest.TestCase):
    def test_offer_intent_noop_when_workflow_off(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_COMMERCIAL_ENABLED": "1",
                "VINOR_COMMERCIAL_WORKFLOW_ENABLED": "0",
            },
            clear=False,
        ):
            from app.workflow.registry import WorkflowRegistry
            from app.conversation.interfaces import INTENT_OFFER
            from app.workflow.interfaces import WF_NONE

            reg = WorkflowRegistry()
            self.assertEqual(reg.resolve_id(INTENT_OFFER), WF_NONE)

    def test_offer_intent_resolves_when_workflow_on(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_COMMERCIAL_ENABLED": "1",
                "VINOR_COMMERCIAL_WORKFLOW_ENABLED": "1",
            },
            clear=False,
        ):
            from app.workflow.registry import WorkflowRegistry
            from app.conversation.interfaces import INTENT_OFFER

            reg = WorkflowRegistry()
            self.assertEqual(reg.resolve_id(INTENT_OFFER), "offer")


class DealPathUntouchedTests(unittest.TestCase):
    def test_propose_deal_still_in_schema(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PARTNER

        names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
        self.assertIn("propose_deal", names)
        self.assertIn("propose_release_deal", names)


if __name__ == "__main__":
    unittest.main()
