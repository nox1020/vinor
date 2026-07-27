# -*- coding: utf-8 -*-
"""Unit tests — helpers زرین‌پال Vinor Plus."""
from __future__ import annotations

import unittest
from datetime import datetime

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


if __name__ == "__main__":
    unittest.main()
