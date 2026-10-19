# -*- coding: utf-8 -*-
"""تأیید و بستن معامله: اول فایل، بعد deal_decision. بستن قبل از معامله نیست."""
from __future__ import annotations

import pytest

PHONE = "09120000001"
VISIT_ID = "deal-v1"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-deal-decision")
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
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _completed_row():
    return {
        "id": VISIT_ID,
        "partner_phone": PHONE,
        "status": "completed",
        "land_code": "9",
        "land_title": "فایل تست معامله",
        "visit_outcome": "interested",
    }


def test_close_not_offered_before_a_deal_exists():
    from app.express_partner.visit_requests import visit_deal_action_flags

    flags = visit_deal_action_flags(_completed_row(), allowed=True)
    assert flags["can_close_deal"] is False
    assert flags["can_confirm_deal"] is True
    assert flags["can_reject_deal"] is True

    started = dict(_completed_row())
    started["deal_decision"] = "approved"
    later = visit_deal_action_flags(started, allowed=True)
    assert later["can_close_deal"] is True
    assert later["can_confirm_deal"] is False


def test_failed_close_leaves_decision_unset_then_confirm_works(monkeypatch):
    from app.express_partner.special_visit_inbox import apply_special_visit_action

    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox.special_can_manage_visit",
        lambda *_a, **_k: True,
    )
    calls = []

    def listing(rec, *, owner_phone, action):
        calls.append((action, str(rec.get("deal_decision") or "")))
        if action == "approve_deal":
            return None, "no_assignment"
        return rec, None

    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox._apply_special_deal_action",
        listing,
    )
    rows = [_completed_row()]
    rec, err = apply_special_visit_action(
        rows,
        owner_phone=PHONE,
        visit_id=VISIT_ID,
        action="close_deal",
    )
    assert rec is None
    assert err == "no_assignment"
    assert not rows[0].get("deal_decision")

    rec, err = apply_special_visit_action(
        rows,
        owner_phone=PHONE,
        visit_id=VISIT_ID,
        action="confirm_deal",
    )
    assert err is None
    assert rec is not None
    assert rows[0].get("deal_decision") == "approved"
    assert calls == [("approve_deal", ""), ("start_deal", "")]


def test_partner_route_returns_listing_error_and_confirm_still_saves(app, client, monkeypatch):
    from app.utils.storage import load_express_visit_requests, save_express_partners, save_express_visit_requests

    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox.inject_visit_deal_chat",
        lambda *_a, **_k: None,
    )
    with app.app_context():
        save_express_partners([{
            "phone": PHONE,
            "name": "ویزیتور",
            "status": "approved",
            "partner_tier": "visitor",
        }])
        save_express_visit_requests([_completed_row()])

    with client.session_transaction() as sess:
        sess["user_phone"] = PHONE

    closed = client.post(
        f"/express/partner/requests/{VISIT_ID}/deal-close",
        json={},
    )
    body = closed.get_json()
    assert closed.status_code == 400
    assert body["ok"] is False
    assert "اجازه" in body["error"]
    with app.app_context():
        stored = load_express_visit_requests()
    assert not (stored[0].get("deal_decision") or "")

    def listing(rec, *, owner_phone, action):
        assert action == "start_deal"
        assert not rec.get("deal_decision")
        return rec, None

    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox._apply_special_deal_action",
        listing,
    )
    confirmed = client.post(
        f"/express/partner/requests/{VISIT_ID}/deal-confirm",
        json={},
    )
    ok = confirmed.get_json()
    assert confirmed.status_code == 200
    assert ok["ok"] is True
    with app.app_context():
        stored = load_express_visit_requests()
    assert stored[0].get("deal_decision") == "approved"
