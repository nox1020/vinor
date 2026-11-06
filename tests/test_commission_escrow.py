# -*- coding: utf-8 -*-
"""بلوکهٔ پورسانت انتشار: کمبود، برداشت، لغو، انقضا، فروش، ادمین، شارژ."""
from __future__ import annotations

import pytest

OWNER = "09120000001"
MARKETER = "09120000002"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-escrow")
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


def _fund(commissions, phone, amount, cid):
    commissions.append({
        "id": cid,
        "commission_type": "manual_adjustment",
        "partner_phone": phone,
        "land_code": "manual",
        "commission_amount": amount,
        "status": "approved",
        "source": "test_fund",
    })


def test_publish_blocked_when_short_and_hold_blocks_withdrawal():
    from app.express_partner.commission_escrow import ensure_hold, held_total
    from app.express_partner.partner_withdrawals import available_for_new_withdrawal

    commissions = []
    _fund(commissions, OWNER, 50_000, 1)
    err, detail = ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=80_000)
    assert err == "wallet_insufficient"
    assert detail["shortfall"] == 30_000
    assert "کمبود" in detail["message"]
    assert held_total(commissions, OWNER) == 0

    err, detail = ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=40_000)
    assert err is None
    assert held_total(commissions, OWNER) == 40_000
    again, again_detail = ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=40_000)
    assert again is None
    assert again_detail["idempotent"] is True
    assert sum(1 for row in commissions if row.get("commission_type") == "escrow_hold") == 1
    assert available_for_new_withdrawal(commissions, [], OWNER) == 10_000


def test_edit_adjusts_hold_up_and_down():
    from app.express_partner.commission_escrow import ensure_hold, held_total

    commissions = []
    _fund(commissions, OWNER, 100_000, 1)
    assert ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=40_000)[0] is None
    err, _detail = ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=90_000)
    assert err is None
    assert held_total(commissions, OWNER) == 90_000
    err, _detail = ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=30_000)
    assert err is None
    assert held_total(commissions, OWNER) == 30_000


def test_cancel_releases_and_open_deal_keeps_hold(monkeypatch):
    from app.express_partner.commission_escrow import (
        STATUS_HELD,
        STATUS_RELEASED,
        ensure_hold,
        release_hold,
    )

    commissions = []
    _fund(commissions, OWNER, 100_000, 1)
    ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=40_000)
    monkeypatch.setattr(
        "app.express_partner.commission_escrow.listing_has_open_deal",
        lambda code: False,
    )
    assert release_hold(commissions, "9", reason="unpublished") is True
    assert commissions[-1]["status"] == STATUS_RELEASED

    ensure_hold(commissions, [], phone=OWNER, land_code="8", amount=20_000)
    monkeypatch.setattr(
        "app.express_partner.commission_escrow.listing_has_open_deal",
        lambda code: code == "8",
    )
    assert release_hold(commissions, "8", reason="expired") is False
    assert any(row.get("land_code") == "8" and row.get("status") == STATUS_HELD for row in commissions)


def test_sale_consumes_hold_once_and_credits_marketer(app):
    from app.express_partner.commission_escrow import STATUS_SETTLED, ensure_hold
    from app.express_partner.deal_wallet import finalize_deal_payout
    from app.express_partner.partner_withdrawals import withdrawable_balance
    from app.utils.storage import save_express_commissions, save_express_partners

    commissions = []
    _fund(commissions, OWNER, 100_000, 1)
    ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=40_000)
    commissions.append({
        "id": 7,
        "commission_type": "deal",
        "partner_phone": MARKETER,
        "land_code": "9",
        "commission_amount": 40_000,
        "sale_amount": 2_000_000,
        "status": "pending",
    })
    with app.app_context():
        save_express_partners([
            {"phone": OWNER, "name": "مالک", "status": "approved", "total_income": 0},
            {"phone": MARKETER, "name": "بازاریاب", "status": "approved", "total_income": 0},
        ])
        save_express_commissions(commissions)
        err, detail = finalize_deal_payout(deal_id=7, owner_phone=OWNER)
        assert err is None
        assert detail["idempotent"] is False
        again, again_detail = finalize_deal_payout(deal_id=7, owner_phone=OWNER)
        assert again is None
        assert again_detail["idempotent"] is True
        from app.utils.storage import load_express_commissions
        rows = load_express_commissions()
    deal = next(row for row in rows if row.get("id") == 7)
    hold = next(row for row in rows if row.get("commission_type") == "escrow_hold" and row.get("land_code") == "9")
    debits = [
        row for row in rows
        if row.get("source") == "deal_final_payout" and int(row.get("commission_amount") or 0) < 0
    ]
    assert deal["status"] == "approved"
    assert hold["status"] == STATUS_SETTLED
    assert len(debits) == 1
    assert int(debits[0]["commission_amount"]) == -40_000
    assert withdrawable_balance(rows, [], OWNER) == 60_000
    assert withdrawable_balance(rows, [], MARKETER) == 40_000


def test_admin_approve_uses_the_hold(app, client, monkeypatch):
    from app.express_partner.commission_escrow import ensure_hold
    from app.utils.storage import load_express_commissions, save_express_commissions, save_express_partners

    commissions = []
    _fund(commissions, OWNER, 80_000, 1)
    ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=30_000)
    commissions.append({
        "id": 8,
        "commission_type": "deal",
        "partner_phone": MARKETER,
        "land_code": "9",
        "commission_amount": 30_000,
        "sale_amount": 1_000_000,
        "status": "pending",
    })
    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: True)
    with app.app_context():
        save_express_partners([
            {"phone": OWNER, "status": "approved", "total_income": 0},
            {"phone": MARKETER, "status": "approved", "total_income": 0},
        ])
        save_express_commissions(commissions)
        from app.utils.storage import save_ads
        save_ads([{"code": "9", "owner": OWNER, "is_express": True, "public": True, "title": "فایل"}])
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    resp = client.post("/admin/express/commissions/8/approve", data={"filter": "pending"})
    assert resp.status_code in (302, 303)
    with app.app_context():
        rows = load_express_commissions()
    deal = next(row for row in rows if row.get("id") == 8)
    hold = next(row for row in rows if row.get("land_code") == "9" and row.get("commission_type") == "escrow_hold")
    assert deal["status"] == "approved"
    assert hold["status"] == "settled"


def test_topup_callback_is_idempotent(monkeypatch):
    from app.express_partner.wallet_topup import complete_wallet_topup

    rows = [{
        "id": 3,
        "commission_type": "manual_adjustment",
        "partner_phone": OWNER,
        "land_code": "wallet",
        "commission_amount": 25_000,
        "status": "pending",
        "source": "wallet_zarinpal",
        "authority": "AUTH1",
        "ref_id": "",
    }]

    def _load():
        return rows

    def _save(items):
        rows[:] = items

    monkeypatch.setattr("app.utils.storage.load_express_commissions", _load)
    monkeypatch.setattr("app.utils.storage.save_express_commissions", _save)
    monkeypatch.setattr(
        "app.express_partner.wallet_topup.payment_verify",
        lambda **_k: {"ok": True, "ref_id": "REF1"},
    )
    monkeypatch.setattr(
        "app.express_partner.wallet_topup.get_zarinpal_settings",
        lambda: {"sandbox": True},
    )
    monkeypatch.setattr(
        "app.express_partner.wallet_topup.effective_merchant_id",
        lambda _cfg=None: "merchant",
    )
    first = complete_wallet_topup("AUTH1", "OK")
    second = complete_wallet_topup("AUTH1", "OK")
    assert first["ok"] is True and first["idempotent"] is False
    assert second["ok"] is True and second["idempotent"] is True
    assert rows[0]["status"] == "approved"
    assert rows[0]["ref_id"] == "REF1"


def test_missing_hold_report_does_not_unpublish():
    from app.express_partner.commission_escrow import listings_missing_hold
    from app.listings.service import is_published_for_sale

    land = {
        "code": "77",
        "title": "قدیمی",
        "owner": OWNER,
        "public": True,
        "is_express": True,
        "owner_home": False,
        "source": "my_property_published",
        "express_status": "approved",
        "price_total": 1_000_000,
        "extras": {"published_for_sale": True, "express_commission_pct": 2, "express_commission_amount": 20_000},
    }
    report = listings_missing_hold([land])
    assert report == [{
        "land_code": "77",
        "owner_phone": OWNER,
        "required_amount": 20_000,
        "title": "قدیمی",
    }]
    assert is_published_for_sale(land) is True
