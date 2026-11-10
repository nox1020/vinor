# -*- coding: utf-8 -*-
"""بازگرداندن بلوکه، قفل شروع معامله، و گزارش ادمین بدون اجرای عنوان آگهی."""
from __future__ import annotations

import threading

import pytest

OWNER = "09120000001"
MARKETER = "09120000002"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-escrow-audit")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setattr(
        "app.express_partner.new_land_sms.notify_all_partners_new_express_land_background",
        lambda *_a, **_k: None,
    )
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _published_archived(**overrides):
    extras = {
        "published_for_sale": True,
        "listed_by_owner": True,
        "express_commission_pct": 2,
        "express_commission_amount": 20_000,
    }
    row = {
        "code": "9",
        "owner": OWNER,
        "title": "فایل",
        "public": True,
        "is_express": True,
        "source": "my_property_published",
        "price_total": 1_000_000,
        "archived": True,
        "is_archived": True,
        "archived_at": "2026-01-01T00:00:00Z",
        "archived_reason": "manual",
        "extras": extras,
    }
    row.update(overrides)
    return row


def _fund(amount, cid):
    return {
        "id": cid,
        "commission_type": "manual_adjustment",
        "partner_phone": OWNER,
        "land_code": "manual",
        "commission_amount": amount,
        "status": "approved",
        "source": "test_fund",
    }


def _holds(rows):
    return [
        row for row in rows
        if row.get("commission_type") == "escrow_hold" and row.get("status") == "held"
    ]


def test_restore_reholds_and_shortfall_unpublishes(app, client):
    from app.listings.service import get_listing, is_published_for_sale, restore_listing
    from app.utils.storage import load_express_commissions, save_ads, save_express_commissions

    with app.app_context():
        save_ads([_published_archived()])
        save_express_commissions([_fund(50_000, 1)])
        land, err, changed = restore_listing("9", phone=OWNER)
    assert err is None and changed is True
    assert is_published_for_sale(land) is True
    assert land.get("archived") is not True
    with app.app_context():
        holds = _holds(load_express_commissions())
    assert len(holds) == 1
    assert holds[0]["commission_amount"] == 20_000
    assert holds[0]["land_code"] == "9"

    with app.app_context():
        again, again_err, again_changed = restore_listing("9", phone=OWNER)
    assert again_err is None and again_changed is False
    with app.app_context():
        assert len(_holds(load_express_commissions())) == 1

    with app.app_context():
        save_ads([_published_archived(code="8")])
        save_express_commissions([])
        short, short_err, short_changed = restore_listing("8", phone=OWNER)
        stored = get_listing("8")
    assert short_err == "wallet_insufficient" and short_changed is True
    assert stored.get("archived") is not True
    assert is_published_for_sale(stored) is False
    assert is_published_for_sale(short) is False
    with app.app_context():
        assert _holds(load_express_commissions()) == []

    with app.app_context():
        save_ads([_published_archived(code="7")])
        save_express_commissions([])
    with client.session_transaction() as sess:
        sess["user_phone"] = OWNER
    resp = client.post("/express/partner/api/my-property/restore", json={"code": "7"})
    body = resp.get_json()
    assert resp.status_code == 400
    assert body["ok"] is False
    assert body["error_code"] == "wallet_insufficient"
    assert body["required_amount"] == 20_000
    assert body["balance"] == 0
    assert body["shortfall"] == 20_000
    assert body["charge_path"] == "/express/partner/wallet/charge"
    assert "کمبود" in body["error"]


def test_restore_does_not_open_a_second_hold(app):
    from app.express_partner.commission_escrow import ensure_hold
    from app.listings.service import is_published_for_sale, restore_listing
    from app.utils.storage import load_express_commissions, save_ads, save_express_commissions

    commissions = [_fund(20_000, 1)]
    assert ensure_hold(commissions, [], phone=OWNER, land_code="9", amount=20_000)[0] is None
    commissions = [row for row in commissions if row.get("commission_type") == "escrow_hold"]
    with app.app_context():
        save_ads([_published_archived()])
        save_express_commissions(commissions)
        land, err, changed = restore_listing("9", phone=OWNER)
        rows = load_express_commissions()
    assert err is None and changed is True
    assert is_published_for_sale(land) is True
    assert len(_holds(rows)) == 1
    assert _holds(rows)[0]["commission_amount"] == 20_000


def test_locked_credit_survives_deal_start(app, monkeypatch):
    from app.express_partner.deal_wallet import commission_store_lock
    from app.express_partner.special_visit_inbox import _start_deal_for_visit
    from app.utils.storage import (
        load_express_commissions,
        save_ads,
        save_express_assignments,
        save_express_commissions,
    )

    monkeypatch.setattr(
        "app.express_partner.admin_action_sms.notify_admin_pending_action",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.express_partner.commission_sms.notify_partner_commission_txn",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.express_partner.visit_sms.notify_partner_land_tx_sms",
        lambda *_a, **_k: None,
    )
    with app.app_context():
        save_ads([{
            "code": "9",
            "owner": OWNER,
            "title": "فایل",
            "price_total": 1_000_000,
            "extras": {"express_commission_amount": 20_000},
        }])
        save_express_assignments([{
            "id": 1,
            "land_code": "9",
            "partner_phone": MARKETER,
            "status": "active",
        }])
        save_express_commissions([])

        entered = threading.Event()
        errors = []

        def credit():
            try:
                with app.app_context():
                    with commission_store_lock():
                        rows = list(load_express_commissions() or [])
                        rows.append(_fund(15_000, 77))
                        save_express_commissions(rows)
                        entered.set()
                        threading.Event().wait(0.4)
            except Exception as exc:
                errors.append(exc)
                entered.set()

        worker = threading.Thread(target=credit)
        worker.start()
        assert entered.wait(5)
        err = _start_deal_for_visit({
            "land_code": "9",
            "partner_phone": MARKETER,
            "partner_name": "مشاور",
        })
        worker.join(5)
        rows = load_express_commissions()
    assert errors == []
    assert err is None
    assert worker.is_alive() is False
    credit_row = next(row for row in rows if row.get("id") == 77)
    assert credit_row["commission_amount"] == 15_000
    assert credit_row["status"] == "approved"
    assert any(
        row.get("commission_type") == "deal" and row.get("status") == "pending"
        for row in rows
    )


def test_escrow_missing_renders_title_as_text(app, client):
    from app.utils.storage import save_ads

    nasty = "{{7*7}}<script>alert(1)</script>"
    with app.app_context():
        save_ads([_published_archived(
            archived=False,
            is_archived=False,
            archived_at="",
            archived_reason="",
            title=nasty,
        )])
    guest = client.get("/admin/express/commissions/escrow-missing")
    assert guest.status_code in (302, 303)
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    page = client.get("/admin/express/commissions/escrow-missing")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "{{7*7}}" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert ">49<" not in html
