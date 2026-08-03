from __future__ import annotations

import os
import tempfile
import unittest

from app.conversation.di import make_conversation_manager
from app.conversation.identity import RuleIdentityResolver
from app.conversation.intent import RuleIntentResolver
from app.conversation.interfaces import (
    ROLE_GUEST,
    ROLE_USER,
    STATE_COLLECTING,
    STATE_COMPLETED,
    WF_PARTNER_ONBOARDING,
    WF_VISIT,
)
from app.conversation.roles import RuleRoleResolver
from app.conversation.session import FileSessionStore, new_session
from app.conversation.workflow import RuleWorkflowResolver


class ConversationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = make_conversation_manager()
        self.tmp = tempfile.mkdtemp()
        # isolate session files
        import app.conversation.session as sess

        self._orig = sess._store_dir
        sess._store_dir = lambda: self.tmp  # type: ignore
        self.store = FileSessionStore()
        self.store.clear("09121112233")

    def tearDown(self) -> None:
        import app.conversation.session as sess

        sess._store_dir = self._orig  # type: ignore
        try:
            self.store.clear("09121112233")
        except Exception:
            pass

    def test_identity_guest(self) -> None:
        info = RuleIdentityResolver().resolve(user_key="guest_abc", audience="public")
        self.assertEqual(info.role, ROLE_GUEST)
        self.assertFalse(info.is_logged_in)

    def test_identity_logged_in_user(self) -> None:
        info = RuleIdentityResolver().resolve(user_key="09121112233", audience="public")
        self.assertIn(info.role, (ROLE_USER, "partner", "premium_partner"))
        self.assertTrue(info.is_logged_in)

    def test_intent_visit_and_search(self) -> None:
        r = RuleIntentResolver()
        self.assertEqual(r.resolve(message="ثبت بازدید می‌خوام").intent, "visit")
        self.assertEqual(r.resolve(message="ویلا در دماوند").intent, "search_property")
        self.assertEqual(r.resolve(message="x", chip_intent="deal").intent, "deal")

    def test_workflow_pass_through_search(self) -> None:
        out = self.mgr.handle(
            message="ویلا تا ۱۵ میلیارد در دماوند",
            user_key="09121112233",
            audience="partner",
        )
        self.assertFalse(out.handled)
        self.assertTrue(out.pass_to_supervisor)
        self.assertEqual(out.extra_tokens, 0)

    def test_partner_onboarding_collects_steps(self) -> None:
        uk = "09121112233"
        out1 = self.mgr.handle(
            message="می‌خواهم همکار شوم درخواست همکاری",
            user_key=uk,
            audience="public",
        )
        self.assertTrue(out1.handled)
        self.assertFalse(out1.pass_to_supervisor)
        self.assertIn("نام", out1.reply)
        self.assertEqual(out1.extra_tokens, 0)

        out2 = self.mgr.handle(message="علی", user_key=uk, audience="public")
        self.assertTrue(out2.handled)
        self.assertIn("نام خانوادگی", out2.reply)

        # fill remaining quickly
        for ans in ("رضایی", "0012345678", "بله"):
            out = self.mgr.handle(message=ans, user_key=uk, audience="public")
        self.assertTrue(out.handled)
        self.assertIsNotNone(out.structured_object)
        self.assertEqual(out.structured_object.get("type"), "PartnerApplication")
        self.assertEqual(out.extra_tokens, 0)

    def test_cancel_workflow(self) -> None:
        uk = "09121112233"
        # Start a form workflow that persists a session, then cancel it.
        self.mgr.handle(
            message="می‌خواهم همکار شوم درخواست همکاری",
            user_key=uk,
            audience="public",
        )
        out = self.mgr.handle(message="لغو کن", user_key=uk, audience="public")
        self.assertTrue(out.handled)
        self.assertIn("لغو", out.reply)

    def test_session_scoped_by_thread_id(self) -> None:
        """Active form on thread A must not leak into thread B."""
        uk = "09121112233"
        self.mgr.handle(
            message="می‌خواهم همکار شوم درخواست همکاری",
            user_key=uk,
            audience="public",
            thread_id="thread-a",
        )
        sess_a = self.store.load(uk, thread_id="thread-a")
        self.assertIsNotNone(sess_a)
        self.assertEqual(sess_a.workflow_id, WF_PARTNER_ONBOARDING)
        sess_b = self.store.load(uk, thread_id="thread-b")
        self.assertIsNone(sess_b)
        # Cancel only thread A — thread B stays empty; legacy key unused.
        self.mgr.handle(
            message="لغو کن",
            user_key=uk,
            audience="public",
            thread_id="thread-a",
        )
        self.assertIsNone(self.store.load(uk, thread_id="thread-a"))

    def test_role_upgrade_order(self) -> None:
        self.assertTrue(RuleRoleResolver.can_upgrade(ROLE_GUEST, ROLE_USER))
        self.assertFalse(RuleRoleResolver.can_upgrade(ROLE_USER, ROLE_GUEST))


if __name__ == "__main__":
    unittest.main()
