# -*- coding: utf-8 -*-
"""Unit tests — helpers زرین‌پال Vinor Plus."""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest import mock

from app.express_partner.plus_subscription import (
    PLUS_RENEW_WINDOW_DAYS,
    backfill_plus_expires_at,
    extend_plus_subscription,
    parse_plus_expires_at,
    plus_renew_allowed,
    plus_subscription_active,
    plus_subscription_view,
    renewal_anchor,
)
from app.express_partner.zarinpal_client import (
    amounts_match,
    is_request_success,
    is_verify_success,
    toman_to_rial,
)


class ZarinPalHelperTests(unittest.TestCase):
    def test_toman_to_rial(self) -> None:
        self.assertEqual(toman_to_rial(990_000), 9_900_000)

    def test_request_success_code(self) -> None:
        self.assertTrue(is_request_success(100))
        self.assertFalse(is_request_success(101))

    def test_verify_success_codes(self) -> None:
        self.assertTrue(is_verify_success(100))
        self.assertTrue(is_verify_success(101))
        self.assertFalse(is_verify_success(-51))

    def test_amounts_match(self) -> None:
        self.assertTrue(amounts_match(1000, 10_000))
        self.assertFalse(amounts_match(1000, 10_001))
        self.assertTrue(amounts_match(990_000, None))


class PlusSubscriptionTests(unittest.TestCase):
    def test_renewal_extends_from_current_expiry(self) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        profile = {"partner_tier": "special", "plus_expires_at": "2026-02-01T12:00:00Z"}
        iso = extend_plus_subscription(profile, 30, now=base)
        self.assertTrue(iso.endswith("Z"))
        self.assertIn("2026-03", iso)

    def test_renewal_from_now_when_expired(self) -> None:
        base = datetime(2026, 3, 15, 12, 0, 0)
        profile = {"partner_tier": "special", "plus_expires_at": "2026-02-01T12:00:00Z"}
        anchor = renewal_anchor(base, parse_plus_expires_at(profile))
        self.assertEqual(anchor, base)
        extend_plus_subscription(profile, 10, now=base)
        self.assertTrue(plus_subscription_active(profile, now=base))

    def test_plus_renew_allowed_only_near_expiry(self) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        far = {
            "status": "approved",
            "partner_tier": "special",
            "plus_expires_at": "2026-02-01T12:00:00Z",
        }
        self.assertFalse(plus_renew_allowed(far, now=base))
        near = {
            "status": "approved",
            "partner_tier": "special",
            "plus_expires_at": "2026-01-08T12:00:00Z",
        }
        self.assertTrue(plus_renew_allowed(near, now=base))
        expired = {
            "status": "approved",
            "partner_tier": "special",
            "plus_expires_at": "2025-12-01T12:00:00Z",
        }
        self.assertTrue(plus_renew_allowed(expired, now=base))
        self.assertEqual(PLUS_RENEW_WINDOW_DAYS, 7)

    def test_legacy_special_without_expiry_gets_backfill(self) -> None:
        base = datetime(2026, 6, 1, 12, 0, 0)
        profile = {"status": "approved", "partner_tier": "special"}
        self.assertFalse(plus_subscription_active(profile, now=base))
        self.assertTrue(backfill_plus_expires_at(profile, days=30, now=base))
        self.assertTrue(plus_subscription_active(profile, now=base))
        view = plus_subscription_view(profile, now=base)
        self.assertEqual(view["status"], "active")
        self.assertIsNotNone(view["days_remaining"])
        self.assertTrue(view["expires_at_jalali"])


from app.express_partner.plus_sms import (
    build_plus_activation_sms_message,
    build_plus_expired_sms_message,
    build_plus_expiry_reminder_sms_message,
    build_plus_renewal_sms_message,
)


class PlusSmsMessageTests(unittest.TestCase):
    def test_activation_message_placeholders(self) -> None:
        msg = build_plus_activation_sms_message(
            name="علی رضایی",
            phone="09121234567",
            expires_jalali="۱۴۰۵/۰۱/۱۵",
            days_remaining="30",
        )
        self.assertIn("Vinor Plus", msg)
        self.assertIn("وینور", msg)

    def test_renewal_custom_template(self) -> None:
        msg = build_plus_renewal_sms_message(
            name="سارا",
            expires_jalali="۱۴۰۵/۰۲/۰۱",
            custom_template="وینور\nتا {expires_jalali}",
        )
        self.assertIn("۱۴۰۵/۰۲/۰۱", msg)

    def test_expiry_reminder_default(self) -> None:
        msg = build_plus_expiry_reminder_sms_message(name="مینا")
        self.assertIn("پایان", msg)

    def test_expired_default(self) -> None:
        msg = build_plus_expired_sms_message()
        self.assertIn("منقضی", msg)


class PlusIsolationTests(unittest.TestCase):
    def test_backfill_only_mutates_target_profile(self) -> None:
        from app.express_partner.plus_subscription import (
            PLUS_EXPIRES_AT_KEY,
            persist_plus_expiry_backfill_for_phone,
        )

        partners = [
            {"phone": "09121111111", "status": "approved", "partner_tier": "special"},
            {"phone": "09122222222", "status": "approved", "partner_tier": "partner"},
        ]
        saved = []

        def _save(items):
            saved.append([dict(p) for p in items])

        with mock.patch(
            "app.utils.storage.load_express_partners", return_value=partners
        ), mock.patch("app.utils.storage.save_express_partners", side_effect=_save):
            self.assertTrue(persist_plus_expiry_backfill_for_phone("09121111111"))

        self.assertEqual(len(saved), 1)
        out = saved[0]
        self.assertTrue(str(out[0].get(PLUS_EXPIRES_AT_KEY) or "").strip())
        self.assertFalse(str(out[1].get(PLUS_EXPIRES_AT_KEY) or "").strip())

    def test_grant_only_updates_matching_phone(self) -> None:
        from app.express_partner.plus_grant import grant_vinor_plus_for_phone

        partners = [
            {"phone": "09121111111", "status": "approved", "partner_tier": "partner"},
            {"phone": "09122222222", "status": "approved", "partner_tier": "partner"},
        ]
        saved = []

        def _save(items):
            saved.append([dict(p) for p in items])

        with mock.patch(
            "app.utils.storage.load_express_partners", return_value=partners
        ), mock.patch("app.utils.storage.save_express_partners", side_effect=_save), mock.patch(
            "app.express_partner.zarinpal_config.plus_subscription_days", return_value=30
        ):
            res = grant_vinor_plus_for_phone("09121111111")

        self.assertTrue(res.get("ok"))
        self.assertEqual(len(saved), 1)
        out = saved[0]
        self.assertEqual(str(out[0].get("partner_tier")), "special")
        self.assertEqual(str(out[1].get("partner_tier")), "partner")

    def test_apply_grant_blocks_session_phone_mismatch(self) -> None:
        from app.express_partner.plus_checkout import _apply_plus_grant_for_txn

        txn = {
            "id": "t1",
            "phone": "09121111111",
            "partner_name": "A",
            "plus_grant_applied": False,
        }
        with mock.patch(
            "app.express_partner.plus_checkout.grant_vinor_plus_for_phone"
        ) as grant_mock:
            out = _apply_plus_grant_for_txn(txn, session_phone="09122222222")
        grant_mock.assert_not_called()
        self.assertEqual(out.get("error"), "session_phone_mismatch")

    def test_sync_session_skips_foreign_plus_profile(self) -> None:
        from app import create_app
        from app.express_partner.partner_session_sync import sync_partner_session_after_plus

        app = create_app()
        app.config["TESTING"] = True
        partners = [
            {
                "phone": "09121111111",
                "status": "approved",
                "partner_tier": "special",
                "plus_expires_at": "2099-01-01T12:00:00Z",
            },
            {"phone": "09122222222", "status": "approved", "partner_tier": "partner"},
        ]
        with app.test_request_context():
            from flask import g, session

            session["user_phone"] = "09122222222"
            with mock.patch(
                "app.utils.storage.load_express_partners", return_value=partners
            ), mock.patch(
                "app.express_partner.plus_subscription.persist_plus_expiry_backfill_for_phone",
                return_value=False,
            ):
                sync_partner_session_after_plus("09121111111")
            prof = getattr(g, "express_partner_profile", None)
            self.assertNotEqual(
                (prof or {}).get("phone"),
                "09121111111",
                "پروفایل کاربر دیگر نباید روی g بنشیند",
            )
            self.assertFalse(session.get("VINOR_PLUS_ACTIVE"))


if __name__ == "__main__":
    unittest.main()
