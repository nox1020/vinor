# -*- coding: utf-8 -*-
"""شارژ تأییدنشده، تسویهٔ یکتا، پیامک معامله، و برچسب‌های قرارداد."""
from __future__ import annotations

import pytest

OWNER = "09120000031"
MARKETER = "09120000032"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-phase3")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_unverified_topup_is_not_credited_and_manual_credit_needs_a_reason(app, client, monkeypatch):
    from app.utils.storage import load_express_commissions, save_express_commissions

    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: True)
    with app.app_context():
        save_express_commissions([{
            "id": 4,
            "commission_type": "manual_adjustment",
            "partner_phone": OWNER,
            "land_code": "wallet",
            "commission_amount": 50_000,
            "status": "pending",
            "source": "wallet_zarinpal",
            "authority": "AUTH",
            "ref_id": "",
        }])
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    blocked = client.post("/admin/express/commissions/4/approve", data={"filter": "pending"})
    assert blocked.status_code in (302, 303)
    with app.app_context():
        row = load_express_commissions()[0]
    assert row["status"] == "pending"
    assert row["ref_id"] == ""
    missing = client.post("/admin/express/wallet/manual-credit", data={"phone": OWNER, "amount": "1000", "reason": "ن"})
    assert missing.status_code in (302, 303)
    with app.app_context():
        assert len(load_express_commissions()) == 1
    credited = client.post(
        "/admin/express/wallet/manual-credit",
        data={"phone": OWNER, "amount": "1000", "reason": "تعدیل پشتیبانی"},
    )
    assert credited.status_code in (302, 303)
    with app.app_context():
        rows = load_express_commissions()
    manual = next(row for row in rows if row.get("source") == "admin_manual_credit")
    assert manual["status"] == "approved"
    assert manual["admin_note"] == "تعدیل پشتیبانی"
    assert manual["commission_amount"] == 1000


def test_second_deal_for_the_same_sale_does_not_pay_again(app):
    from app.express_partner.commission_escrow import ensure_hold
    from app.express_partner.deal_wallet import finalize_deal_payout
    from app.utils.storage import load_express_commissions, save_express_commissions, save_express_partners

    rows = []
    rows.append({
        "id": 1,
        "commission_type": "manual_adjustment",
        "partner_phone": OWNER,
        "commission_amount": 100_000,
        "status": "approved",
        "source": "test_fund",
    })
    ensure_hold(rows, [], phone=OWNER, land_code="9", amount=40_000)
    rows.append({
        "id": 7,
        "commission_type": "deal",
        "partner_phone": MARKETER,
        "land_code": "9",
        "visit_id": "visit-1",
        "commission_amount": 40_000,
        "status": "pending",
    })
    rows.append({
        "id": 8,
        "commission_type": "deal",
        "partner_phone": MARKETER,
        "land_code": "9",
        "visit_id": "visit-1",
        "commission_amount": 40_000,
        "status": "pending",
    })
    with app.app_context():
        save_express_partners([
            {"phone": OWNER, "status": "approved", "total_income": 0},
            {"phone": MARKETER, "status": "approved", "total_income": 0},
        ])
        save_express_commissions(rows)
        first, _detail = finalize_deal_payout(deal_id=7, owner_phone=OWNER)
        second, second_detail = finalize_deal_payout(deal_id=8, owner_phone=OWNER)
        stored = load_express_commissions()
    assert first is None
    assert second == "already_settled"
    debits = [row for row in stored if int(row.get("commission_amount") or 0) < 0]
    assert len(debits) == 1
    assert second_detail["message"]
    again, again_detail = None, None
    with app.app_context():
        again, again_detail = finalize_deal_payout(deal_id=7, owner_phone=OWNER)
        stored = load_express_commissions()
    assert again is None and again_detail["idempotent"] is True
    assert len([row for row in stored if int(row.get("commission_amount") or 0) < 0]) == 1


def test_admin_deal_approve_closes_the_visit_and_sends_sms(app, client, monkeypatch):
    from app.express_partner.commission_escrow import ensure_hold
    from app.utils.storage import (
        load_express_visit_requests,
        save_ads,
        save_express_commissions,
        save_express_partners,
        save_express_visit_requests,
    )

    sms = []
    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "app.express_partner.commission_sms.notify_partner_commission_txn",
        lambda **kw: sms.append(kw) or {"ok": True},
    )
    rows = [{
        "id": 1,
        "commission_type": "manual_adjustment",
        "partner_phone": OWNER,
        "commission_amount": 80_000,
        "status": "approved",
        "source": "test_fund",
    }]
    ensure_hold(rows, [], phone=OWNER, land_code="9", amount=30_000)
    rows.append({
        "id": 8,
        "commission_type": "deal",
        "partner_phone": MARKETER,
        "land_code": "9",
        "visit_id": "visit-9",
        "commission_amount": 30_000,
        "sale_amount": 1_000_000,
        "status": "pending",
    })
    with app.app_context():
        save_express_partners([
            {"phone": OWNER, "status": "approved", "total_income": 0},
            {"phone": MARKETER, "status": "approved", "total_income": 0},
        ])
        save_ads([{"code": "9", "owner": OWNER, "is_express": True, "public": True, "title": "فایل"}])
        save_express_commissions(rows)
        save_express_visit_requests([{
            "id": "visit-9",
            "partner_phone": MARKETER,
            "land_code": "9",
            "status": "completed",
            "deal_decision": "approved",
        }])
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    resp = client.post("/admin/express/commissions/8/approve", data={"filter": "pending"})
    assert resp.status_code in (302, 303)
    with app.app_context():
        visit = load_express_visit_requests()[0]
    assert visit["deal_decision"] == "closed"
    assert sms and sms[0]["event"] == "commission_approved"


def test_pending_commission_sms_is_sent_when_enabled_and_skipped_when_disabled(app, monkeypatch):
    from app.express_partner.commission_sms import notify_partner_commission_txn

    sent = []
    monkeypatch.setattr(
        "app.express_partner.commission_sms.send_sms_direct",
        lambda **kw: sent.append(kw) or {"ok": True, "status": 200, "body": {}},
    )
    monkeypatch.setattr(
        "app.express_partner.commission_sms._partner_sms_allowed",
        lambda: True,
    )
    with app.app_context():
        result = notify_partner_commission_txn(
            partner_phone=MARKETER,
            event="commission_pending",
            amount=12000,
            land_code="9",
            reference_id="7",
        )
    assert result["skipped"] is False
    assert sent and "12،000" in sent[0]["message"]
    sent.clear()
    monkeypatch.setattr(
        "app.express_partner.commission_sms._partner_sms_allowed",
        lambda: False,
    )
    with app.app_context():
        skipped = notify_partner_commission_txn(
            partner_phone=MARKETER,
            event="commission_pending",
            amount=12000,
            land_code="9",
        )
    assert skipped["skipped"] is True
    assert skipped["error"] == "sms_disabled"
    assert sent == []


def test_contract_uses_archive_hide_labels_and_grouped_amounts():
    from app.express_partner.follow_card_contract import build_follow_contract

    card = build_follow_contract({
        "id": "v",
        "direction": "outgoing",
        "status": "pending",
        "can_archive": True,
        "can_remove": True,
    })
    labels = [row["label"] for row in card["secondary_actions"] + card["danger_actions"]]
    assert "بایگانی این پیگیری" in labels
    assert "حذف از پیگیری من" in labels
    closed = build_follow_contract({
        "id": "v",
        "direction": "outgoing",
        "status": "completed",
        "deal_decision": "closed",
        "deal_commission_amount": 25000,
        "can_archive": True,
    })
    assert "۲۵" not in closed["status_label"] or "25،000" in closed["status_label"]
    assert "25،000" in closed["status_label"]
    assert any(row["label"] == "بایگانی این پیگیری" for row in closed["secondary_actions"])
    archived = build_follow_contract({
        "id": "v",
        "direction": "outgoing",
        "status": "pending",
        "archived": True,
        "read_only": True,
        "can_archive": True,
    })
    assert archived["secondary_actions"][0]["label"] == "بازگرداندن به پیگیری"
