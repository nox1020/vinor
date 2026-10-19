# -*- coding: utf-8 -*-
"""معامله دریافتی: تأیید نهایی همان شروع فایل است و بدون انتساب نشان داده نمی‌شود."""
from __future__ import annotations

import pytest

OWNER = "09121111000"
REQUESTER = "09123333000"
LAND = "90"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-incoming-deal")
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


def _visit(vid, code, partner=REQUESTER):
    return {
        "id": vid,
        "partner_phone": partner,
        "partner_name": "مشاور",
        "land_code": code,
        "land_title": "فایل قرارداد",
        "status": "completed",
        "visit_outcome": "interested",
        "plus_user_phone": OWNER,
        "owner_phone": OWNER,
        "customer_phone": "09120000071",
        "customer_name": "خریدار",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-03T00:00:00Z",
    }


def _land():
    return {
        "code": LAND,
        "title": "فایل قرارداد",
        "owner": OWNER,
        "is_express": True,
        "public": True,
        "source": "express",
        "price_total": 2_000_000,
        "extras": {"previous_code": "89", "express_commission_pct": 2},
    }


def _seed(app, visits, assignments):
    from app.utils.storage import (
        save_ads,
        save_express_assignments,
        save_express_partners,
        save_express_visit_requests,
    )

    with app.app_context():
        save_express_partners([{
            "phone": OWNER,
            "name": "پلاس",
            "status": "approved",
            "partner_tier": "special",
            "plus_expires_at": "2099-01-01T00:00:00Z",
        }, {
            "phone": REQUESTER,
            "name": "مشاور",
            "status": "approved",
            "partner_tier": "visitor",
        }])
        save_ads([_land()])
        save_express_assignments(assignments)
        save_express_visit_requests(visits)


def _login(client, phone=OWNER):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


def test_confirm_hidden_and_no_assignment_does_not_decide(app, client):
    from app.express_partner.special_visit_inbox import apply_special_visit_action, listing_deal_error_fa
    from app.utils.storage import load_express_visit_requests

    _seed(app, [_visit("bare", "89")], [])
    _login(client)
    cards = {
        card["id"]: card
        for card in client.get("/express/partner/api/requests/data").get_json()["cards"]
    }
    card = cards["bare"]
    assert card["direction"] == "incoming"
    assert card["pipeline_tab"] == "deals"
    assert card["status_label"] == "علاقه‌مند — وقت دوم یا قرارداد"
    assert card["can_confirm_deal"] is False
    assert card["can_start_deal"] is False
    assert card["can_reject_deal"] is True
    page = client.get("/express/partner/requests").get_data(as_text=True)
    assert "/inbox-visits/bare/confirm_deal" not in page
    assert "/inbox-visits/bare/start_deal" not in page

    with app.app_context():
        rows = load_express_visit_requests()
        rec, err = apply_special_visit_action(
            rows, owner_phone=OWNER, visit_id="bare", action="confirm_deal",
        )
    assert rec is None
    assert err == "no_assignment"
    assert listing_deal_error_fa(err) == (
        "این همکار روی فایل اختصاص ندارد؛ معامله فقط از سمت همکار اختصاص‌یافته ممکن است."
    )
    assert "ثبت معامله روی فایل ممکن نشد" not in listing_deal_error_fa(err)


def test_confirm_without_a_file_is_no_land(app):
    from app.express_partner.special_visit_inbox import apply_special_visit_action, listing_deal_error_fa
    from app.utils.storage import load_express_visit_requests

    _seed(app, [_visit("calendar", "")], [])
    with app.app_context():
        rows = load_express_visit_requests()
        _rec, err = apply_special_visit_action(
            rows, owner_phone=OWNER, visit_id="calendar", action="confirm_deal",
        )
    assert err == "no_land"
    assert listing_deal_error_fa(err) == "این پرونده به فایلی وصل نیست."


def test_confirm_matches_previous_code_and_98_phone(app, client):
    from app.utils.storage import load_express_assignments, load_express_visit_requests

    _seed(
        app,
        [_visit("deal1", "89")],
        [{
            "id": 1,
            "land_code": LAND,
            "partner_phone": "989123333000",
            "status": "active",
        }],
    )
    _login(client)
    card = next(
        card for card in client.get("/express/partner/api/requests/data").get_json()["cards"]
        if card["id"] == "deal1"
    )
    assert card["can_start_deal"] is True
    assert card["can_confirm_deal"] is True

    saved = client.post("/express/partner/inbox-visits/deal1/confirm_deal", data={})
    assert saved.status_code == 302
    page = client.get(saved.headers["Location"]).get_data(as_text=True)
    assert "معامله تأیید شد." in page
    assert "ثبت معامله روی فایل ممکن نشد" not in page
    with app.app_context():
        row = next(item for item in load_express_visit_requests() if item["id"] == "deal1")
        assignment = load_express_assignments()[0]
    assert row.get("deal_decision") == "approved"
    assert assignment["status"] == "in_transaction"
    assert assignment["land_code"] == LAND
