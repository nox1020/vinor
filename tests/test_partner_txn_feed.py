# -*- coding: utf-8 -*-
"""Smoke asserts for partner commissions transactions feed."""
from __future__ import annotations

import unittest


class PartnerTxnFeedTests(unittest.TestCase):
    def test_feed_includes_paid_partial_negative_and_withdrawal_bank(self):
        from app.express_partner.partner_withdrawals import (
            build_partner_txn_feed,
            commission_to_txn_row,
            partner_txn_feed_summary,
        )

        phone = "09121112233"
        commissions = [
            {
                "id": 1,
                "partner_phone": phone,
                "status": "paid",
                "commission_amount": 0,
                "partial_paid_total": 12_000_000,
                "sale_amount": 400_000_000,
                "commission_pct": 3,
                "land_code": "A1",
                "paid_at": "2026-07-01T12:00:00",
                "created_at": "2026-06-01T12:00:00",
            },
            {
                "id": 2,
                "partner_phone": phone,
                "status": "approved",
                "commission_amount": 3_000_000,
                "partial_paid_total": 1_000_000,
                "sale_amount": 100_000_000,
                "commission_pct": 4,
                "land_code": "A2",
                "approved_at": "2026-07-10T12:00:00",
                "created_at": "2026-07-01T12:00:00",
            },
            {
                "id": 3,
                "partner_phone": phone,
                "status": "approved",
                "commission_type": "manual_adjustment",
                "commission_amount": -2_500_000,
                "land_code": "manual",
                "approved_at": "2026-07-11T12:00:00",
                "created_at": "2026-07-11T12:00:00",
                "admin_note": "اصلاح موجودی",
            },
            {
                "id": 4,
                "partner_phone": phone,
                "status": "approved",
                "commission_type": "manual_adjustment",
                "commission_amount": "not-a-number",
                "land_code": "manual",
                "created_at": "2026-07-12T12:00:00",
            },
        ]
        withdrawals = [
            {
                "id": "wd-paid-1",
                "phone": phone,
                "status": "paid",
                "amount": 12_000_000,
                "bank_summary": "ملت ****1111",
                "bank_name": "ملت",
                "masked_pan": "****1111",
                "holder_name": "تست",
                "updated_at": "2026-07-01T13:00:00",
                "created_at": "2026-06-28T10:00:00",
                "commission_allocated_amount": 12_000_000,
            },
            {
                "id": "wd-pending-1",
                "phone": phone,
                "status": "pending",
                "amount": 5_000_000,
                "bank_summary": "ملی ****2222",
                "bank_name": "ملی",
                "masked_pan": "****2222",
                "created_at": "2026-07-20T10:00:00",
            },
        ]

        paid_row = commission_to_txn_row(commissions[0])
        self.assertIsNotNone(paid_row)
        self.assertEqual(paid_row["commission_amount"], 12_000_000)

        partial_row = commission_to_txn_row(commissions[1])
        self.assertIsNotNone(partial_row)
        self.assertEqual(partial_row["commission_amount"], 4_000_000)
        self.assertEqual(partial_row["partial_paid_display"], 1_000_000)

        neg_row = commission_to_txn_row(commissions[2])
        self.assertIsNotNone(neg_row)
        self.assertEqual(neg_row["commission_amount"], -2_500_000)

        # corrupt adjustment amount → skipped (0), must not raise
        self.assertIsNone(commission_to_txn_row(commissions[3]))

        feed = build_partner_txn_feed(commissions, withdrawals, phone)
        kinds = {(r.get("txn_type"), r.get("status")) for r in feed}
        self.assertIn(("commission", "paid"), kinds)
        self.assertIn(("withdrawal", "withdrawal"), kinds)
        self.assertIn(("withdrawal_request", "pending"), kinds)

        paid_wd = next(r for r in feed if r.get("txn_type") == "withdrawal")
        self.assertEqual(paid_wd.get("bank_name"), "ملت")
        self.assertEqual(paid_wd.get("masked_pan"), "****1111")
        self.assertTrue(isinstance(paid_wd.get("_txn_detail"), dict))
        self.assertEqual(paid_wd["_txn_detail"].get("amount_sign"), "-")

        summary = partner_txn_feed_summary(feed)
        self.assertGreaterEqual(summary["all"], 4)
        self.assertGreaterEqual(summary["withdrawal"], 2)

    def test_empty_partner_feed(self):
        from app.express_partner.partner_withdrawals import build_partner_txn_feed

        self.assertEqual(build_partner_txn_feed([], [], "09120000000"), [])
        self.assertEqual(build_partner_txn_feed([None, "x"], [{"bad": 1}], ""), [])


if __name__ == "__main__":
    unittest.main()
