# -*- coding: utf-8 -*-
"""Phase 4 Closing & Finance — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class ClosingFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_CLOSING")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.closing import config as cfg

            self.assertTrue(cfg.closing_enabled())
            self.assertTrue(cfg.closing_ui_enabled())
            self.assertTrue(cfg.closing_ai_tools_enabled())
            self.assertTrue(cfg.closing_activity_hook_enabled())
            self.assertTrue(cfg.closing_deal_bridge_enabled())
            self.assertTrue(cfg.closing_reservation_bridge_enabled())

    def test_master_off_disables_nested(self) -> None:
        with mock.patch.dict(os.environ, {"VINOR_CLOSING_ENABLED": "0"}, clear=False):
            from app.closing import config as cfg

            self.assertFalse(cfg.closing_enabled())
            self.assertFalse(cfg.closing_ui_enabled())
            self.assertFalse(cfg.closing_ai_tools_enabled())


class ClosingCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_CLOSING_ENABLED": "1",
            "VINOR_CLOSING_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_deal_contract_payment_settlement_flow(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.closing.service import (
                add_payment,
                create_contract,
                list_partner_deals,
                mark_payment_paid,
                open_settlement,
                update_contract_document,
                upsert_deal,
            )

            deal = upsert_deal(
                land_code="401",
                partner_phone="09121111111",
                sale_amount=1_000_000_000,
                commission_id="99",
                status="in_transaction",
                assignment_status="in_transaction",
            )
            self.assertIsNotNone(deal)
            self.assertEqual(deal.land_code, "401")
            self.assertEqual(deal.status, "in_transaction")

            contract = create_contract(deal_id=deal.id, title="مبایعه‌نامه", actor_key="09121111111")
            self.assertIsNotNone(contract)
            self.assertEqual(contract.document_status, "draft")

            updated = update_contract_document(contract.id, document_status="signed")
            self.assertIsNotNone(updated)
            self.assertEqual(updated.document_status, "signed")
            self.assertTrue(updated.signed_at)

            pay = add_payment(
                deal_id=deal.id,
                amount=100_000_000,
                milestone_label="بیعانه",
                actor_key="09121111111",
            )
            self.assertIsNotNone(pay)
            paid = mark_payment_paid(pay.id)
            self.assertEqual(paid.status, "paid")

            settlement = open_settlement(
                deal_id=deal.id,
                parties=[{"role": "partner", "amount": 50_000_000, "phone": "09121111111"}],
                withdrawal_id="w1",
                actor_key="09121111111",
            )
            self.assertIsNotNone(settlement)
            self.assertEqual(settlement.withdrawal_id, "w1")
            self.assertEqual(settlement.total_amount, 50_000_000)

            deals = list_partner_deals("09121111111")
            self.assertGreaterEqual(len(deals), 1)

    def test_bridge_does_not_mutate_assignment_list(self) -> None:
        """Deal bridge only writes closing JSON — assignment list untouched."""
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.closing.deal_bridge import maybe_sync_deal_from_commission

            assignments = [{"land_code": "402", "status": "active", "partner_phone": "09122222222"}]
            snapshot = [dict(a) for a in assignments]
            deal = maybe_sync_deal_from_commission(
                partner_phone="09122222222",
                land_code="402",
                commission_id="7",
                sale_amount=500,
                assignment_status="in_transaction",
                deal_status="in_transaction",
            )
            self.assertIsNotNone(deal)
            self.assertEqual(assignments, snapshot)
            self.assertEqual(deal.commission_id, "7")


class ClosingDealBridgeFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_CLOSING_ENABLED": "1",
            "VINOR_CLOSING_DEAL_BRIDGE_ENABLED": "1",
            "VINOR_CLOSING_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_bridge_off_no_deal(self) -> None:
        env = {**self._env, "VINOR_CLOSING_DEAL_BRIDGE_ENABLED": "0"}
        with mock.patch.dict(os.environ, env, clear=False):
            from app.closing.deal_bridge import maybe_sync_deal_from_commission
            from app.closing.service import list_partner_deals

            maybe_sync_deal_from_commission(
                partner_phone="09123333333",
                land_code="403",
                commission_id="1",
            )
            self.assertEqual(list_partner_deals("09123333333"), [])

    def test_reservation_link_no_mark_in_tx(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.closing.deal_bridge import maybe_link_reservation_to_deal
            from app.closing.service import list_partner_deals

            deal = maybe_link_reservation_to_deal(
                reservation_id="res1",
                partner_phone="09124444444",
                land_code="404",
                offer_id="off1",
                buyer_phone="09125555555",
            )
            self.assertIsNotNone(deal)
            self.assertEqual(deal.reservation_id, "res1")
            self.assertEqual(deal.status, "draft")
            self.assertEqual(list_partner_deals("09124444444")[0].offer_id, "off1")


class ClosingAiToolsFlagTests(unittest.TestCase):
    def test_tools_absent_when_off(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_CLOSING_ENABLED": "0",
                "VINOR_CLOSING_AI_TOOLS_ENABLED": "0",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_deal", names)
            self.assertNotIn("propose_contract", names)
            self.assertNotIn("propose_payment_milestone", names)
            self.assertNotIn("propose_settlement", names)

    def test_tools_present_when_on(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_CLOSING_ENABLED": "1",
                "VINOR_CLOSING_AI_TOOLS_ENABLED": "1",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_deal", names)
            self.assertIn("propose_release_deal", names)
            self.assertNotIn("propose_contract", names)
            self.assertNotIn("propose_payment_milestone", names)
            self.assertNotIn("propose_settlement", names)


class DealPathUntouchedTests(unittest.TestCase):
    def test_propose_deal_still_in_schema(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PARTNER

        names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
        self.assertIn("propose_deal", names)
        self.assertIn("propose_release_deal", names)


if __name__ == "__main__":
    unittest.main()
