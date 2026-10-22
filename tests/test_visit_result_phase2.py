# -*- coding: utf-8 -*-
"""Phase 2 Visit Result / No-Show — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class VisitResultFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_VISIT_RESULT")
            and not k.startswith("VINOR_VISIT_NO_SHOW")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.visit_result import config as cfg

            self.assertTrue(cfg.visit_result_enabled())
            self.assertTrue(cfg.visit_result_ui_enabled())
            self.assertTrue(cfg.visit_result_ai_tools_enabled())
            self.assertTrue(cfg.visit_no_show_status_enabled())
            self.assertTrue(cfg.visit_result_activity_hook_enabled())


class VisitStatusesAdditiveTests(unittest.TestCase):
    def test_original_five_statuses_preserved(self) -> None:
        from app.express_partner.visit_requests import (
            APPROVED_STATUS,
            CANCELLED_STATUS,
            COMPLETED_STATUS,
            DONE_PENDING_STATUS,
            NO_SHOW_STATUS,
            PENDING_STATUS,
            ADMIN_VISIT_STATUSES,
        )

        original = {
            PENDING_STATUS,
            APPROVED_STATUS,
            DONE_PENDING_STATUS,
            COMPLETED_STATUS,
            CANCELLED_STATUS,
        }
        self.assertEqual(
            original,
            {"pending", "approved", "done_pending", "completed", "cancelled"},
        )
        self.assertEqual(NO_SHOW_STATUS, "no_show")
        self.assertTrue(original.issubset(ADMIN_VISIT_STATUSES))
        self.assertIn(NO_SHOW_STATUS, ADMIN_VISIT_STATUSES)


class VisitResultStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_VISIT_RESULT_ENABLED": "1",
            "VINOR_VISIT_RESULT_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_upsert_result(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.visit_result.service import get_result, register_result

            r1 = register_result(
                visit_request_id="v100",
                partner_phone="09121111111",
                land_code="10",
                outcome="interested",
                notes="first",
                source="partner",
            )
            self.assertIsNotNone(r1)
            assert r1 is not None
            r2 = register_result(
                visit_request_id="v100",
                partner_phone="09121111111",
                land_code="10",
                outcome="follow_up",
                notes="updated",
                source="partner",
            )
            self.assertIsNotNone(r2)
            assert r2 is not None
            self.assertEqual(r1.id, r2.id)
            self.assertEqual(r2.outcome, "follow_up")
            got = get_result("v100")
            self.assertIsNotNone(got)
            assert got is not None
            self.assertEqual(got.outcome, "follow_up")


class VisitNoShowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_VISIT_RESULT_ENABLED": "1",
            "VINOR_VISIT_NO_SHOW_STATUS_ENABLED": "1",
            "VINOR_VISIT_RESULT_ACTIVITY_HOOK_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_mark_no_show_no_commission_path(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.express_partner.visit_requests import (
                APPROVED_STATUS,
                NO_SHOW_STATUS,
                mark_visit_no_show,
                visit_tx_mode,
            )
            from app.visit_result.service import register_no_show

            requests = [
                {
                    "id": "vnoshow1",
                    "partner_phone": "09123333333",
                    "land_code": "55",
                    "land_title": "Test",
                    "status": APPROVED_STATUS,
                    "customer_name": "Ali",
                }
            ]
            rec, result, err = register_no_show(
                requests,
                visit_request_id="vnoshow1",
                notes="customer absent",
                source="partner",
            )
            self.assertIsNone(err)
            self.assertIsNotNone(rec)
            assert rec is not None
            self.assertEqual(rec.get("status"), NO_SHOW_STATUS)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.outcome, "no_show")
            # commission helper must not be implied — status is not completed
            self.assertNotEqual(rec.get("status"), "completed")

            mode = visit_tx_mode(
                "active",
                has_visit_awaiting_admin=False,
                has_approved_visit=False,
                has_visit_done_pending=False,
                has_completed_visit=False,
                has_visit_no_show=True,
                is_approved=True,
                is_sold=False,
            )
            self.assertEqual(mode, "visit_no_show")

    def test_no_show_disabled_when_flag_off(self) -> None:
        env = {**self._env, "VINOR_VISIT_RESULT_ENABLED": "0"}
        with mock.patch.dict(os.environ, env, clear=False):
            from app.express_partner.visit_requests import APPROVED_STATUS, mark_visit_no_show

            requests = [
                {
                    "id": "v2",
                    "partner_phone": "09124444444",
                    "land_code": "66",
                    "status": APPROVED_STATUS,
                }
            ]
            rec, err = mark_visit_no_show(requests, visit_request_id="v2")
            self.assertIsNone(rec)
            self.assertEqual(err, "disabled")
            self.assertEqual(requests[0]["status"], APPROVED_STATUS)

    def test_admin_cannot_transition_to_no_show_when_off(self) -> None:
        env = {**self._env, "VINOR_VISIT_RESULT_ENABLED": "0"}
        with mock.patch.dict(os.environ, env, clear=False):
            from app.express_partner.visit_requests import (
                APPROVED_STATUS,
                NO_SHOW_STATUS,
                admin_can_transition_visit,
            )

            self.assertFalse(admin_can_transition_visit(APPROVED_STATUS, NO_SHOW_STATUS))


class VisitResultAiToolsFlagTests(unittest.TestCase):
    def test_tools_absent_when_flag_off(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_VISIT_RESULT_ENABLED": "0",
                "VINOR_VISIT_RESULT_AI_TOOLS_ENABLED": "0",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_visit_request", names)
            self.assertIn("propose_complete_visit", names)
            self.assertNotIn("propose_visit_result", names)
            self.assertNotIn("propose_no_show", names)

    def test_tools_present_when_flag_on(self) -> None:
        """نتیجه بازدید در schema چت است وقتی فلگ روشن است (مثل CRM)."""
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_VISIT_RESULT_ENABLED": "1",
                "VINOR_VISIT_RESULT_AI_TOOLS_ENABLED": "1",
            },
            clear=False,
        ):
            from app.ai.agent_tools import tools_schema_for_voice
            from app.ai.audience import VOICE_PARTNER
            from app.ai.goal import CORE_TOOLS_PARTNER, EXTENDED_CHAT_TOOLS

            names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
            self.assertIn("propose_complete_visit", names)
            self.assertIn("propose_visit_result", names)
            self.assertIn("propose_no_show", names)
            self.assertTrue(set(names).isdisjoint(EXTENDED_CHAT_TOOLS))
            self.assertTrue(set(names) <= CORE_TOOLS_PARTNER)


class VisitResultActivityHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_VISIT_RESULT_ENABLED": "1",
            "VINOR_VISIT_RESULT_ACTIVITY_HOOK_ENABLED": "1",
            "VINOR_FOUNDATION_ENABLED": "1",
            "VINOR_ACTIVITY_STORE_ENABLED": "1",
            "VINOR_TIMELINE_STORE_ENABLED": "1",
            "INSTANCE_PATH": self.tmp,
        }

    def test_register_result_emits_activity(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.visit_result.service import register_result
            from app.foundation.activity_store import list_activities

            register_result(
                visit_request_id="vact1",
                partner_phone="09125555555",
                land_code="77",
                outcome="not_interested",
                actor_key="09125555555",
            )
            acts = list_activities(actor_key="09125555555", limit=20)
            self.assertTrue(any(a.action == "visit_result_registered" for a in acts))


class VisitResultChatPathTests(unittest.TestCase):
    def test_parse_outcome_phrases(self) -> None:
        from app.ai.agent_tools import parse_visit_outcome_from_text

        self.assertEqual(parse_visit_outcome_from_text("مشتری علاقه‌مند بود"), "interested")
        self.assertEqual(parse_visit_outcome_from_text("بی‌علاقه بود"), "not_interested")
        self.assertEqual(parse_visit_outcome_from_text("باید دوباره پیگیری کنیم"), "follow_up")
        self.assertEqual(parse_visit_outcome_from_text("نیومد"), "no_show")
        self.assertEqual(parse_visit_outcome_from_text("نتیجه بازدید را ثبت کن"), "")

    def test_home_peygiri_stays_in_chat(self) -> None:
        from app.express_partner.sales_coach import build_home_ai_quick_prompts

        # The follow-up tile was removed from home on purpose (b91c3c8);
        # follow-up now lives inside chat, so home must not link out of it.
        items = build_home_ai_quick_prompts(is_approved=True)
        self.assertIsNone(next((i for i in items if i.get("label") == "پیگیری"), None))
        self.assertTrue(items)
        self.assertTrue(all(i.get("href", "").find("/visit") < 0 for i in items))


if __name__ == "__main__":
    unittest.main()
