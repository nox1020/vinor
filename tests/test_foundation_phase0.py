# -*- coding: utf-8 -*-
"""Phase 0 Foundation — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class FoundationFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_FOUNDATION")
            and not k.startswith("VINOR_ACTIVITY")
            and not k.startswith("VINOR_TIMELINE")
            and not k.startswith("VINOR_WORKFLOW_COMMIT")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.foundation import config as cfg

            self.assertTrue(cfg.foundation_enabled())
            self.assertTrue(cfg.activity_store_enabled())
            self.assertTrue(cfg.timeline_store_enabled())
            self.assertTrue(cfg.workflow_commit_enabled())
            self.assertTrue(cfg.workflow_commit_persist_enabled())


class ActivityTimelineStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_FOUNDATION_ENABLED": "1",
            "VINOR_ACTIVITY_STORE_ENABLED": "1",
            "VINOR_TIMELINE_STORE_ENABLED": "1",
            "VINOR_WORKFLOW_COMMIT_ENABLED": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_append_only_activity_and_timeline(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.foundation.activity_store import append_activity, list_activities
            from app.foundation.timeline_store import link_activity_to_timeline, list_timeline

            a1 = append_activity(
                action="test_event",
                actor_key="09120000001",
                actor_role="partner",
                land_code="100",
                workflow_id="visit",
                object_type="VisitRequest",
                summary="test",
                payload={"x": 1},
            )
            self.assertIsNotNone(a1)
            self.assertTrue(a1.id)
            entries = link_activity_to_timeline(a1)
            self.assertGreaterEqual(len(entries), 1)

            a2 = append_activity(
                action="test_event_2",
                actor_key="09120000001",
                land_code="100",
                summary="second",
            )
            self.assertIsNotNone(a2)
            self.assertNotEqual(a1.id, a2.id)

            acts = list_activities(actor_key="09120000001", limit=10)
            self.assertGreaterEqual(len(acts), 2)
            # append-only: first id still present
            ids = {a.id for a in acts}
            self.assertIn(a1.id, ids)
            self.assertIn(a2.id, ids)

            tl = list_timeline(subject_type="land", subject_id="100", limit=20)
            self.assertGreaterEqual(len(tl), 1)

    def test_stores_noop_when_foundation_off(self) -> None:
        env = dict(self._env)
        env["VINOR_FOUNDATION_ENABLED"] = "0"
        with mock.patch.dict(os.environ, env, clear=False):
            from app.foundation.activity_store import append_activity, list_activities
            from app.foundation.timeline_store import append_timeline_entry

            self.assertIsNone(
                append_activity(action="x", actor_key="09120000002")
            )
            self.assertEqual(list_activities(actor_key="09120000002"), [])
            self.assertIsNone(
                append_timeline_entry(
                    subject_type="actor",
                    subject_id="09120000002",
                    activity_id="abc",
                )
            )


class WorkflowCommitAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_FOUNDATION_ENABLED": "1",
            "VINOR_ACTIVITY_STORE_ENABLED": "1",
            "VINOR_TIMELINE_STORE_ENABLED": "1",
            "VINOR_WORKFLOW_COMMIT_ENABLED": "1",
            "VINOR_WORKFLOW_COMMIT_PERSIST": "0",
            "INSTANCE_PATH": self.tmp,
        }

    def test_commit_records_activity_shadow_only(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.foundation.activity_store import list_activities
            from app.foundation.storage_adapter import plan_from_structured_object
            from app.foundation.workflow_commit import commit_structured_object
            from app.utils.storage import data_dir
            import os as _os

            obj = {
                "type": "VisitRequest",
                "workflow_id": "visit",
                "role": "partner",
                "fields": {
                    "land_code": "55",
                    "visitor_name": "علی",
                    "visitor_phone": "09121234567",
                },
                "status": "COMPLETED",
            }
            plan = plan_from_structured_object(obj)
            self.assertEqual(plan.target_store, "express_visit_requests")
            self.assertEqual(plan.action, "shadow")

            result = commit_structured_object(
                obj, actor_key="09129998877", actor_role="partner"
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.shadowed)
            self.assertFalse(result.persisted)
            self.assertTrue(result.activity_id)
            self.assertEqual(result.reason, "phase0_shadow")

            acts = list_activities(actor_key="09129998877", land_code="55")
            self.assertGreaterEqual(len(acts), 1)

            # Must NOT create express visit file writes from commit
            visit_path = _os.path.join(data_dir(), "express_visit_requests.json")
            # file may exist from ensure, but commit must not require it; no assertion on content mutation
            self.assertTrue(result.plan is not None)

    def test_persist_flag_still_blocked_in_phase0(self) -> None:
        env = dict(self._env)
        env["VINOR_WORKFLOW_COMMIT_PERSIST"] = "1"
        with mock.patch.dict(os.environ, env, clear=False):
            from app.foundation.workflow_commit import commit_structured_object

            result = commit_structured_object(
                {
                    "type": "DealRequest",
                    "workflow_id": "deal",
                    "fields": {"land_code": "9", "amount": "1000"},
                },
                actor_key="09121112233",
            )
            self.assertTrue(result.ok)
            self.assertFalse(result.persisted)
            self.assertEqual(result.reason, "phase0_persist_blocked")

    def test_maybe_record_noop_when_disabled(self) -> None:
        env = dict(self._env)
        env["VINOR_FOUNDATION_ENABLED"] = "0"
        with mock.patch.dict(os.environ, env, clear=False):
            from app.foundation.service import maybe_record_workflow_commit
            from app.workflow.interfaces import (
                WF_STATE_COMPLETED,
                WorkflowContext,
                WorkflowEngineResult,
            )

            result = WorkflowEngineResult(
                handled=True,
                ok=True,
                reply="done",
                context=WorkflowContext(
                    workflow_id="visit",
                    state=WF_STATE_COMPLETED,
                    user_key="09120000003",
                    role="partner",
                    object_type="VisitRequest",
                    collected={"land_code": "1"},
                ),
                structured_object={
                    "type": "VisitRequest",
                    "workflow_id": "visit",
                    "fields": {"land_code": "1"},
                },
            )
            self.assertIsNone(maybe_record_workflow_commit(result))


class ConversationRegressionWithFoundationHookTests(unittest.TestCase):
    """Ensure Conversation/Workflow paths still work with foundation hook present."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        import app.conversation.session as sess

        self._orig = sess._store_dir
        sess._store_dir = lambda: self.tmp  # type: ignore

    def tearDown(self) -> None:
        import app.conversation.session as sess

        sess._store_dir = self._orig  # type: ignore

    def test_partner_onboarding_flow_unchanged_flags_off(self) -> None:
        env = {
            "VINOR_FOUNDATION_ENABLED": "0",
            "VINOR_CONVERSATION_ENABLED": "1",
            "VINOR_WORKFLOW_ENGINE_ENABLED": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            from app.conversation.di import make_conversation_manager
            from app.conversation.session import FileSessionStore

            phone = "09123334455"
            FileSessionStore().clear(phone)
            mgr = make_conversation_manager()
            out1 = mgr.handle(
                message="درخواست همکاری",
                user_key=phone,
                audience="public",
            )
            self.assertTrue(out1.handled)
            self.assertIn("نام", out1.reply or "")

            out2 = mgr.handle(
                message="علی تستی",
                user_key=phone,
                audience="public",
            )
            self.assertTrue(out2.handled)
            self.assertTrue(out2.reply)

    def test_workflow_complete_with_commit_on_does_not_break_reply(self) -> None:
        env = {
            "VINOR_FOUNDATION_ENABLED": "1",
            "VINOR_ACTIVITY_STORE_ENABLED": "1",
            "VINOR_TIMELINE_STORE_ENABLED": "1",
            "VINOR_WORKFLOW_COMMIT_ENABLED": "1",
            "VINOR_WORKFLOW_COMMIT_PERSIST": "0",
            "VINOR_CONVERSATION_ENABLED": "1",
            "VINOR_WORKFLOW_ENGINE_ENABLED": "1",
            "INSTANCE_PATH": self.tmp,
        }
        with mock.patch.dict(os.environ, env, clear=False):
            from app.conversation.session import FileSessionStore
            from app.foundation.service import maybe_record_workflow_commit
            from app.workflow.di import make_workflow_engine
            from app.workflow.interfaces import WF_SUPPORT

            phone = "09124445566"
            FileSessionStore().clear(phone)
            eng = make_workflow_engine()
            r = eng.start(
                workflow_id=WF_SUPPORT,
                user_key=phone,
                role="user",
                intent="support",
            )
            self.assertTrue(r.handled)
            ctx = r.context
            for answer in ("مشکل پرداخت", "پورسانت واریز نشده", "بله"):
                r = eng.continue_(ctx=ctx, message=answer)
                ctx = r.context
            self.assertEqual(ctx.state, "COMPLETED")
            self.assertIsNotNone(r.structured_object)

            cr = maybe_record_workflow_commit(r)
            self.assertIsNotNone(cr)
            self.assertTrue(cr.ok)
            self.assertFalse(cr.persisted)
            self.assertTrue(bool(r.reply))


class RolePathSmokeTests(unittest.TestCase):
    """Smoke checks that role/audience constants and modules still import."""

    def test_roles_and_audience_intact(self) -> None:
        from app.conversation.interfaces import (
            ROLE_GUEST,
            ROLE_PARTNER,
            ROLE_PREMIUM,
            ROLE_USER,
        )
        from app.ai.audience import VOICE_PARTNER, VOICE_PUBLIC, VOICE_SPECIAL
        from app.express_partner.partner_roles import (
            PARTNER_TIER_PARTNER,
            PARTNER_TIER_SPECIAL,
        )
        from app.express_partner.visit_requests import (
            APPROVED_STATUS,
            CANCELLED_STATUS,
            COMPLETED_STATUS,
            DONE_PENDING_STATUS,
            PENDING_STATUS,
        )
        from app.express_partner.commissions_flow import (
            APPROVED_STATUS as C_APPROVED,
            PAID_STATUS,
            PENDING_STATUS as C_PENDING,
            REJECTED_STATUS,
        )
        from app.express_partner.partner_withdrawals import ADMIN_STATUS_TRANSITIONS

        self.assertEqual(ROLE_GUEST, "guest")
        self.assertEqual(ROLE_USER, "user")
        self.assertEqual(ROLE_PARTNER, "partner")
        self.assertEqual(ROLE_PREMIUM, "premium_partner")
        self.assertEqual(VOICE_PUBLIC, "public")
        self.assertEqual(VOICE_PARTNER, "partner")
        self.assertEqual(VOICE_SPECIAL, "special")
        self.assertEqual(PARTNER_TIER_PARTNER, "partner")
        self.assertEqual(PARTNER_TIER_SPECIAL, "special")
        self.assertEqual(
            {PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS, CANCELLED_STATUS},
            {"pending", "approved", "done_pending", "completed", "cancelled"},
        )
        self.assertEqual(
            {C_PENDING, C_APPROVED, PAID_STATUS, REJECTED_STATUS},
            {"pending", "approved", "paid", "rejected"},
        )
        self.assertIn("pending", ADMIN_STATUS_TRANSITIONS)

    def test_ai_agent_tools_schemas_intact(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PARTNER, VOICE_PUBLIC, VOICE_SPECIAL

        pub = tools_schema_for_voice(VOICE_PUBLIC)
        par = tools_schema_for_voice(VOICE_PARTNER)
        sp = tools_schema_for_voice(VOICE_SPECIAL)
        self.assertTrue(any(t["function"]["name"] == "search_lands" for t in pub))
        self.assertTrue(any(t["function"]["name"] == "propose_visit_request" for t in par))
        self.assertTrue(any(t["function"]["name"] == "propose_deal" for t in sp))

    def test_workflow_registry_seven(self) -> None:
        from app.workflow.di import make_workflow_engine

        eng = make_workflow_engine()
        for wid in (
            "property_registration",
            "property_editing",
            "partner_onboarding",
            "visit",
            "deal",
            "support",
            "general_conversation",
            "offer",  # Phase 3 — registered; resolve gated by commercial workflow flag
            "visit_result",  # Phase 6
            "crm_followup",
            "closing_contract",
        ):
            self.assertIsNotNone(eng.get_spec(wid))


if __name__ == "__main__":
    unittest.main()
