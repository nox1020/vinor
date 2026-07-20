from __future__ import annotations

import tempfile
import unittest

from app.conversation.di import make_conversation_manager
from app.conversation.session import FileSessionStore
from app.workflow.di import make_workflow_engine
from app.workflow.interfaces import (
    WF_PARTNER_ONBOARDING,
    WF_PROPERTY_EDITING,
    WF_PROPERTY_REGISTRATION,
    WF_STATE_WAITING_USER,
)
from app.workflow.validation import (
    validate_area,
    validate_national_id,
    validate_phone,
    validate_price,
)


class WorkflowEngineUnitTests(unittest.TestCase):
    def test_validators(self) -> None:
        self.assertTrue(validate_price("۱۵ میلیارد").ok or validate_price("15000000000").ok)
        self.assertTrue(validate_price("2500000000").ok)
        self.assertFalse(validate_price("abc").ok)
        self.assertTrue(validate_area("۵۰۰ متر").ok)
        self.assertFalse(validate_area("هیچ").ok)
        self.assertTrue(validate_phone("09121234567").ok)
        self.assertFalse(validate_phone("123").ok)
        self.assertTrue(validate_national_id("0012345678").ok)
        self.assertFalse(validate_national_id("1111111111").ok)

    def test_registry_has_seven(self) -> None:
        eng = make_workflow_engine()
        ids = {
            "property_registration",
            "property_editing",
            "partner_onboarding",
            "visit",
            "deal",
            "support",
            "general_conversation",
        }
        for wid in ids:
            if wid == "general_conversation":
                self.assertIsNotNone(eng.get_spec(wid))
            else:
                self.assertIsNotNone(eng.get_spec(wid))
                self.assertFalse(eng.get_spec(wid).pass_through)


class WorkflowEngineFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = make_workflow_engine()
        self.tmp = tempfile.mkdtemp()
        import app.conversation.session as sess

        self._orig = sess._store_dir
        sess._store_dir = lambda: self.tmp  # type: ignore
        self.mgr = make_conversation_manager()
        FileSessionStore().clear("09123334455")

    def tearDown(self) -> None:
        import app.conversation.session as sess

        sess._store_dir = self._orig  # type: ignore
        FileSessionStore().clear("09123334455")

    def test_start_registration_asks_type(self) -> None:
        r = self.engine.start(
            workflow_id=WF_PROPERTY_REGISTRATION,
            user_key="09123334455",
            role="user",
            intent="register_property",
        )
        self.assertTrue(r.handled)
        self.assertIn("نوع ملک", r.reply)
        self.assertEqual(r.context.state, WF_STATE_WAITING_USER)
        self.assertEqual(r.extra_tokens, 0)

    def test_validation_rejects_bad_price(self) -> None:
        start = self.engine.start(
            workflow_id=WF_PROPERTY_REGISTRATION,
            user_key="u1",
            role="user",
            intent="register_property",
        )
        # fill until price
        ctx = start.context
        answers = ["ویلا", "دماوند", "گرمابسرد", "500", "نه قیمت"]
        for ans in answers:
            out = self.engine.continue_(ctx=ctx, message=ans)
            ctx = out.context
            if not out.ok:
                break
        self.assertFalse(out.ok)
        self.assertTrue(out.observability.get("validation_errors"))

    def test_partner_complete_via_manager(self) -> None:
        uk = "09123334455"
        out1 = self.mgr.handle(
            message="می‌خواهم همکار شوم درخواست همکاری",
            user_key=uk,
            audience="public",
        )
        self.assertTrue(out1.handled)
        self.assertIn("نام", out1.reply)
        for ans in ("علی رضایی", "0012345678", "تهران", "۳ سال مشاور", "بله"):
            out = self.mgr.handle(message=ans, user_key=uk, audience="public")
        self.assertTrue(out.handled)
        self.assertIsNotNone(out.structured_object)
        self.assertEqual(out.structured_object.get("type"), "PartnerApplication")
        self.assertEqual(out.extra_tokens, 0)

    def test_edit_property_intent(self) -> None:
        # Chat-First: land_code is not asked in-form — hand off to Supervisor/tools.
        out = self.mgr.handle(
            message="ویرایش فایل ملک",
            user_key="09123334455",
            audience="partner",
        )
        self.assertFalse(out.handled)
        self.assertTrue(out.pass_to_supervisor)
        self.assertNotIn("کد فایل", out.reply or "")

    def test_search_pass_through(self) -> None:
        out = self.mgr.handle(
            message="ویلا تا ۱۵ میلیارد در دماوند",
            user_key="09123334455",
            audience="partner",
        )
        self.assertFalse(out.handled)
        self.assertTrue(out.pass_to_supervisor)

    def test_cancel(self) -> None:
        uk = "09123334455"
        # Partner visit uses tools/cards (no form session) — cancel a real form instead.
        self.mgr.handle(
            message="می‌خواهم همکار شوم درخواست همکاری",
            user_key=uk,
            audience="public",
        )
        out = self.mgr.handle(message="لغو کن", user_key=uk, audience="public")
        self.assertTrue(out.handled)
        self.assertIn("لغو", out.reply)

    def test_partner_visit_uses_tools_cards(self) -> None:
        out = self.mgr.handle(
            message="ثبت بازدید",
            user_key="09123334455",
            audience="partner",
            chip_intent="visit",
        )
        self.assertFalse(out.handled)
        self.assertTrue(out.pass_to_supervisor)
        self.assertEqual(
            (out.observability or {}).get("skip_reason"),
            "partner_chat_tools_only",
        )


class ConversationCompatTests(unittest.TestCase):
    """Phase 11.5 compatibility still holds with Workflow Engine."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        import app.conversation.session as sess

        self._orig = sess._store_dir
        sess._store_dir = lambda: self.tmp  # type: ignore
        self.mgr = make_conversation_manager()

    def tearDown(self) -> None:
        import app.conversation.session as sess

        sess._store_dir = self._orig  # type: ignore

    def test_existing_conversation_tests_smoke(self) -> None:
        out = self.mgr.handle(message="سلام", user_key="guest_x", audience="public")
        # greeting → general → pass supervisor
        self.assertFalse(out.handled)
        self.assertTrue(out.pass_to_supervisor)


if __name__ == "__main__":
    unittest.main()
