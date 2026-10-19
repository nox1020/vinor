# -*- coding: utf-8 -*-
"""تأیید نهایی معامله فقط بعد از انتقال پورسانت از کیف پول مالک."""
from __future__ import annotations

import pytest

OWNER = "09121111000"
ADVISOR = "09123333000"
LAND = "77"
COMMISSION = 200_000
FUNDED = 500_000


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-deal-wallet")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setattr(
        "app.express_partner.new_land_sms.notify_all_partners_new_express_land_background",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.express_partner.visit_sms.notify_partner_land_tx_sms",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.express_partner.admin_action_sms.notify_admin_pending_action",
        lambda *_a, **_k: {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(
        "app.express_partner.commission_sms.notify_partner_commission_txn",
        lambda *_a, **_k: {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox.inject_visit_deal_chat",
        lambda *_a, **_k: None,
    )
    import app.express_partner.special_visit_inbox as inbox
    import app.utils.storage as storage

    monkeypatch.setattr(inbox, "load_express_partners", storage.load_express_partners)
    monkeypatch.setattr(inbox, "save_express_partners", storage.save_express_partners)
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _seed(app, *, funded: int):
    from app.utils.storage import (
        save_ads,
        save_express_assignments,
        save_express_commissions,
        save_express_partners,
        save_express_visit_requests,
    )

    with app.app_context():
        save_express_partners([
            {
                "phone": OWNER,
                "name": "پلاس",
                "status": "approved",
                "partner_tier": "special",
                "plus_expires_at": "2099-01-01T00:00:00Z",
                "total_income": 0,
            },
            {
                "phone": ADVISOR,
                "name": "مشاور",
                "status": "approved",
                "partner_tier": "visitor",
                "total_income": 0,
            },
        ])
        save_ads([{
            "code": LAND,
            "title": "فایل پورسانت",
            "owner": OWNER,
            "is_express": True,
            "public": True,
            "source": "express",
            "price_total": 5_000_000,
            "extras": {"express_commission_amount": COMMISSION},
        }])
        save_express_assignments([{
            "id": 1,
            "land_code": LAND,
            "partner_phone": ADVISOR,
            "status": "in_transaction",
        }])
        save_express_commissions([
            {
                "id": 1,
                "commission_type": "manual_adjustment",
                "partner_phone": OWNER,
                "land_code": "manual",
                "commission_amount": funded,
                "status": "approved",
                "source": "test_fund",
            },
            {
                "id": 2,
                "commission_type": "deal",
                "partner_phone": ADVISOR,
                "land_code": LAND,
                "commission_amount": COMMISSION,
                "sale_amount": 5_000_000,
                "status": "pending",
                "source": "special_inbox",
            },
        ])
        save_express_visit_requests([{
            "id": "dealw",
            "partner_phone": ADVISOR,
            "partner_name": "مشاور",
            "land_code": LAND,
            "land_title": "فایل پورسانت",
            "status": "completed",
            "visit_outcome": "interested",
            "plus_user_phone": OWNER,
            "owner_phone": OWNER,
            "customer_phone": "09120000081",
            "customer_name": "خریدار",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-03T00:00:00Z",
        }])


def _login(client):
    with client.session_transaction() as sess:
        sess["user_phone"] = OWNER


def _balances(app):
    from app.express_partner.partner_withdrawals import withdrawable_balance
    from app.utils.storage import load_express_commissions, load_express_partners, load_partner_withdrawals

    with app.app_context():
        commissions = load_express_commissions() or []
        withdrawals = load_partner_withdrawals() or []
        partners = {
            row.get("phone"): row
            for row in (load_express_partners() or [])
            if isinstance(row, dict)
        }
    return {
        "owner": withdrawable_balance(commissions, withdrawals, OWNER),
        "advisor": withdrawable_balance(commissions, withdrawals, ADVISOR),
        "advisor_income": int((partners.get(ADVISOR) or {}).get("total_income") or 0),
        "commissions": commissions,
    }


def _payouts(commissions):
    return [
        row for row in commissions
        if isinstance(row, dict) and row.get("source") == "deal_final_payout"
    ]


def _deal(commissions):
    return next(row for row in commissions if row.get("id") == 2)


def test_sufficient_wallet_pays_once_and_confirms(app, client):
    _seed(app, funded=FUNDED)
    _login(client)
    card = next(
        row for row in client.get("/express/partner/api/requests/data").get_json()["cards"]
        if row["id"] == "dealw"
    )
    assert card["required_commission"] == COMMISSION
    assert card["owner_wallet_balance"] == FUNDED
    assert card["can_final_confirm"] is True
    assert card["can_approve_deal"] is True

    saved = client.post("/express/partner/inbox-visits/dealw/approve_deal", data={})
    assert saved.status_code == 302
    page = client.get(saved.headers["Location"]).get_data(as_text=True)
    assert "پورسانت از کیف پول شما به کیف پول مشاور منتقل شد" in page

    state = _balances(app)
    assert state["owner"] == FUNDED - COMMISSION
    assert state["advisor"] == COMMISSION
    assert state["advisor_income"] == COMMISSION
    deal = _deal(state["commissions"])
    assert deal["status"] == "approved"
    payouts = _payouts(state["commissions"])
    assert len(payouts) == 1
    assert payouts[0]["commission_amount"] == -COMMISSION
    assert payouts[0]["payout_deal_id"] == "2"
    assert payouts[0]["partner_phone"] == OWNER
    assert sum(1 for row in state["commissions"] if row.get("commission_type") == "deal") == 1
    with app.app_context():
        from app.utils.storage import load_express_assignments
        assignment = load_express_assignments()[0]
    assert assignment["status"] == "sold"

    again = client.post("/express/partner/inbox-visits/dealw/approve_deal", data={})
    assert again.status_code == 302
    state = _balances(app)
    assert state["owner"] == FUNDED - COMMISSION
    assert state["advisor"] == COMMISSION
    assert state["advisor_income"] == COMMISSION
    assert len(_payouts(state["commissions"])) == 1

    closed = client.post("/express/partner/inbox-visits/dealw/close_deal", data={})
    assert closed.status_code == 302
    with app.app_context():
        from app.utils.storage import load_express_visit_requests
        visit = load_express_visit_requests()[0]
    assert visit.get("deal_decision") == "closed"
    state = _balances(app)
    assert len(_payouts(state["commissions"])) == 1
    assert state["owner"] == FUNDED - COMMISSION


def test_insufficient_wallet_does_not_confirm(app, client):
    _seed(app, funded=100_000)
    _login(client)
    card = next(
        row for row in client.get("/express/partner/api/requests/data").get_json()["cards"]
        if row["id"] == "dealw"
    )
    assert card["can_final_confirm"] is False
    assert card["required_commission"] == COMMISSION
    assert card["owner_wallet_balance"] == 100_000
    assert card["wallet_shortfall"] == 100_000
    assert card["wallet_error"] == "wallet_insufficient"
    from app.express_partner.deal_wallet import wallet_insufficient_message
    assert card["final_confirm_message"] == wallet_insufficient_message(COMMISSION, 100_000)

    page = client.get("/express/partner/requests").get_data(as_text=True)
    assert "برای تأیید نهایی، ابتدا کیف پول خود را به مبلغ پورسانت" in page
    assert "شارژ کیف پول" in page
    assert "/express/partner/commissions" in page

    saved = client.post(
        "/express/partner/inbox-visits/dealw/approve_deal",
        data={},
        headers={"Accept": "application/json"},
    )
    assert saved.status_code == 400
    body = saved.get_json()
    assert body["ok"] is False
    assert body["error"] == "wallet_insufficient"
    assert body["required_amount"] == COMMISSION
    assert body["balance"] == 100_000
    assert body["shortfall"] == 100_000
    assert "برای تأیید نهایی" in body["message"]

    state = _balances(app)
    assert state["owner"] == 100_000
    assert state["advisor"] == 0
    assert state["advisor_income"] == 0
    assert _deal(state["commissions"])["status"] == "pending"
    assert _payouts(state["commissions"]) == []
    with app.app_context():
        from app.utils.storage import load_express_visit_requests
        visit = load_express_visit_requests()[0]
    assert not visit.get("deal_decision")


def test_retry_does_not_double_pay(app, client):
    _seed(app, funded=FUNDED)
    _login(client)
    first = client.post("/express/partner/inbox-visits/dealw/approve_deal", data={})
    second = client.post("/express/partner/inbox-visits/dealw/approve_deal", data={})
    assert first.status_code == 302
    assert second.status_code == 302
    state = _balances(app)
    assert len(_payouts(state["commissions"])) == 1
    assert state["owner"] == FUNDED - COMMISSION
    assert state["advisor"] == COMMISSION
    assert state["advisor_income"] == COMMISSION


def test_failure_midway_rolls_back(app, client, monkeypatch):
    _seed(app, funded=FUNDED)
    _login(client)

    def _boom(stage):
        if stage == "saved":
            raise RuntimeError("disk failed after write")

    monkeypatch.setattr("app.express_partner.deal_wallet.commit_guard", _boom)
    from app.express_partner.special_visit_inbox import apply_special_visit_action
    from app.utils.storage import load_express_visit_requests

    with app.app_context():
        rows = load_express_visit_requests()
        rec, err = apply_special_visit_action(
            rows, owner_phone=OWNER, visit_id="dealw", action="approve_deal",
        )
    assert rec is None
    assert err == "failed"
    state = _balances(app)
    assert state["owner"] == FUNDED
    assert state["advisor"] == 0
    assert state["advisor_income"] == 0
    assert _deal(state["commissions"])["status"] == "pending"
    assert _payouts(state["commissions"]) == []
    with app.app_context():
        from app.utils.storage import load_express_assignments
        assert load_express_assignments()[0]["status"] == "in_transaction"
