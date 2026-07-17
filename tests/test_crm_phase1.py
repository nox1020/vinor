# -*- coding: utf-8 -*-
"""Phase 1 CRM — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class CrmFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_CRM")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.crm import config as cfg

            self.assertTrue(cfg.crm_enabled())
            self.assertTrue(cfg.crm_ui_enabled())
            self.assertTrue(cfg.crm_ai_tools_enabled())
            self.assertTrue(cfg.crm_visit_sync_enabled())
            self.assertTrue(cfg.crm_activity_hook_enabled())


class CrmStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_CRM_ENABLED": "1",
            "VINOR_CRM_UI_ENABLED": "1",
            "VINOR_CRM_AI_TOOLS_ENABLED": "0",
            "VINOR_CRM_VISIT_SYNC_ENABLED": "1",
            "VINOR_CRM_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_contact_call_followup_crud(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.crm.service import (
                list_partner_calls,
                list_partner_customers,
                list_partner_followups,
                log_call,
                schedule_followup,
                upsert_contact,
            )
            from app.crm.config import VISIT_CALL_TARGET

            c = upsert_contact(
                partner_phone="09121111111",
                customer_phone="09122222222",
                first_name="علی",
                last_name="رضایی",
                source="manual",
            )
            self.assertIsNotNone(c)
            assert c is not None
            self.assertTrue(c.id)
            customers = list_partner_customers("09121111111")
            self.assertEqual(len(customers), 1)

            call = log_call(
                partner_phone="09121111111",
                contact_id=c.id,
                outcome="answered",
                notes="هماهنگی بازدید",
            )
            self.assertIsNotNone(call)
            assert call is not None
            self.assertEqual(call.to_number, VISIT_CALL_TARGET)
            self.assertEqual(len(list_partner_calls("09121111111", contact_id=c.id)), 1)

            fu = schedule_followup(
                partner_phone="09121111111",
                contact_id=c.id,
                due_at="2026-08-01",
                notes="تماس مجدد",
            )
            self.assertIsNotNone(fu)
            self.assertEqual(
                len(list_partner_followups("09121111111", contact_id=c.id, status="pending")),
                1,
            )

            # upsert same phone updates, does not duplicate
            c2 = upsert_contact(
                partner_phone="09121111111",
                customer_phone="09122222222",
                first_name="علی",
                last_name="رضایی",
                source="visit",
                visit_id="visitabc",
            )
            self.assertIsNotNone(c2)
            assert c2 is not None
            self.assertEqual(c.id, c2.id)
            self.assertIn("visitabc", c2.visit_ids)
            self.assertEqual(len(list_partner_customers("09121111111")), 1)


class CrmVisitSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_CRM_ENABLED": "1",
            "VINOR_CRM_VISIT_SYNC_ENABLED": "1",
            "VINOR_CRM_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_sync_from_visit_does_not_mutate_visit(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.crm.visit_sync import sync_contact_from_visit
            from app.crm.service import list_partner_customers

            visit = {
                "id": "v1",
                "partner_phone": "09123333333",
                "customer_phone": "09124444444",
                "customer_first_name": "سارا",
                "customer_last_name": "محمدی",
                "customer_name": "سارا محمدی",
                "land_code": "100",
                "visit_date": "2026-08-10",
                "status": "approved",
            }
            snapshot = dict(visit)
            contact = sync_contact_from_visit(visit)
            self.assertIsNotNone(contact)
            self.assertEqual(visit, snapshot)  # Visit untouched
            customers = list_partner_customers("09123333333")
            self.assertEqual(len(customers), 1)
            self.assertEqual(customers[0].source, "visit")
            self.assertIn("v1", customers[0].visit_ids)

    def test_sync_noop_when_crm_off(self) -> None:
        env = {**self._env, "VINOR_CRM_ENABLED": "0"}
        with mock.patch.dict(os.environ, env, clear=False):
            from app.crm.visit_sync import sync_contact_from_visit

            out = sync_contact_from_visit(
                {
                    "id": "v2",
                    "partner_phone": "09125555555",
                    "customer_phone": "09126666666",
                    "customer_first_name": "A",
                    "customer_last_name": "B",
                }
            )
            self.assertIsNone(out)


class CrmActivityHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_CRM_ENABLED": "1",
            "VINOR_CRM_ACTIVITY_HOOK_ENABLED": "1",
            "VINOR_FOUNDATION_ENABLED": "1",
            "VINOR_ACTIVITY_STORE_ENABLED": "1",
            "VINOR_TIMELINE_STORE_ENABLED": "1",
            "INSTANCE_PATH": self.tmp,
        }

    def test_log_call_emits_activity(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.crm.service import log_call, upsert_contact
            from app.foundation.activity_store import list_activities

            c = upsert_contact(
                partner_phone="09127777777",
                customer_phone="09128888888",
                first_name="N",
                last_name="M",
            )
            self.assertIsNotNone(c)
            assert c is not None
            call = log_call(
                partner_phone="09127777777",
                contact_id=c.id,
                outcome="answered",
            )
            self.assertIsNotNone(call)
            acts = list_activities(actor_key="09127777777", limit=20)
            actions = {a.action for a in acts}
            self.assertIn("crm_contact_upsert", actions)
            self.assertIn("crm_call_logged", actions)


class CrmAiToolsFlagTests(unittest.TestCase):
    def test_crm_tools_absent_when_flag_off(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_CRM_ENABLED": "0",
                "VINOR_CRM_AI_TOOLS_ENABLED": "0",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_visit_request", names)
            self.assertNotIn("propose_log_call", names)
            self.assertNotIn("propose_followup", names)

    def test_crm_tools_present_when_flag_on(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_CRM_ENABLED": "1",
                "VINOR_CRM_AI_TOOLS_ENABLED": "1",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_log_call", names)
            self.assertIn("propose_followup", names)
            # existing tools still present
            self.assertIn("propose_visit_request", names)
            self.assertIn("propose_deal", names)


class CrmRegressionSafetyTests(unittest.TestCase):
    def test_visit_statuses_unchanged(self) -> None:
        from app.express_partner.visit_requests import (
            APPROVED_STATUS,
            CANCELLED_STATUS,
            COMPLETED_STATUS,
            DONE_PENDING_STATUS,
            PENDING_STATUS,
        )

        self.assertEqual(
            {PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS, CANCELLED_STATUS},
            {"pending", "approved", "done_pending", "completed", "cancelled"},
        )


if __name__ == "__main__":
    unittest.main()
