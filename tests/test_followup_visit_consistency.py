# -*- coding: utf-8 -*-
"""Follow-up cards: two-step sale, listing-owner payout, canonical phones, locked writes."""
from __future__ import annotations

import pytest

OWNER = "09121111000"
ADVISOR = "09123333000"


def test_sale_flags_follow_deal_decision():
    from app.express_partner.visit_requests import visit_deal_action_flags

    row = {"id": "v", "status": "completed", "visit_outcome": "interested"}
    before = visit_deal_action_flags(row, allowed=True)
    assert before["can_confirm_deal"] is True
    assert before["can_close_deal"] is False
    assert before["can_reject_deal"] is False

    opened = dict(row)
    opened["deal_decision"] = "approved"
    after = visit_deal_action_flags(opened, allowed=True)
    assert after["can_confirm_deal"] is False
    assert after["can_reject_deal"] is False
    assert after["can_close_deal"] is True


def test_pending_commission_does_not_offer_close_before_approval(monkeypatch):
    from app.express_partner.special_visit_inbox import visits_for_special_owner

    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox._visit_row_for_plus_owner",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox.load_express_commissions_cached",
        lambda: [{
            "id": 2,
            "commission_type": "deal",
            "partner_phone": ADVISOR,
            "land_code": "9",
            "commission_amount": 10,
            "status": "pending",
        }],
    )
    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox.load_express_assignments",
        lambda: [],
    )
    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox.load_partner_withdrawals",
        lambda: [],
    )
    row = {
        "id": "v",
        "status": "completed",
        "visit_outcome": "interested",
        "partner_phone": ADVISOR,
        "owner_phone": OWNER,
        "land_code": "9",
    }
    cards = visits_for_special_owner(OWNER, visit_rows=[row])
    card = cards[0]
    assert card["can_confirm_deal"] is True
    assert card["can_close_deal"] is False
    assert card["can_approve_deal"] is False


def test_create_stores_canonical_phone_and_old_rows_still_match(monkeypatch):
    from datetime import date, timedelta

    from app.express_partner.visit_requests import (
        _phones_match,
        create_visit_request,
        partner_cancel_own_visit,
    )

    when = date.today() + timedelta(days=2)
    monkeypatch.setattr(
        "app.express_partner.visit_requests.is_visit_weekday_allowed",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "app.express_partner.visit_requests.resolve_free_visit_slot",
        lambda *a, **k: (when, 10),
    )
    assert _phones_match("+989123334444", "09123334444")
    assert _phones_match("989123334444", "09123334444")
    rows = []
    rec, err = create_visit_request(
        rows,
        partner_phone="+989123334444",
        partner_name="همکار",
        land_code="",
        land_title="",
        visit_date=when.isoformat(),
        customer_first_name="الف",
        customer_last_name="ب",
        customer_phone="09120000000",
        require_customer=True,
        plus_user_phone="989121111000",
    )
    assert err is None, err
    assert rec["partner_phone"] == "09123334444"
    updated, cancel_err = partner_cancel_own_visit(
        rows, request_id=rec["id"], partner_phone="989123334444"
    )
    assert cancel_err is None
    assert updated["status"] == "cancelled"


def test_deal_close_debits_the_listing_owner_not_the_requester(app, client, monkeypatch):
    from app.utils.storage import save_ads, save_express_visit_requests

    seen = {}

    def _payout(*, deal_id, owner_phone):
        seen["owner"] = owner_phone
        return None, {"idempotent": True, "land_code": "9", "partner_phone": ADVISOR}

    monkeypatch.setattr(
        "app.express_partner.deal_wallet.finalize_deal_payout",
        _payout,
    )
    from app.utils.storage import save_express_commissions, save_express_partners

    with app.app_context():
        save_express_partners([
            {
                "phone": ADVISOR,
                "name": "بازاریاب",
                "status": "approved",
                "partner_tier": "partner",
            },
            {
                "phone": OWNER,
                "name": "مالک",
                "status": "approved",
                "partner_tier": "partner",
            },
        ])
        save_ads([{
            "code": "9",
            "title": "فایل",
            "owner_phone": OWNER,
            "is_express": True,
            "public": True,
        }])
        save_express_commissions([{
            "id": 2,
            "commission_type": "deal",
            "partner_phone": ADVISOR,
            "land_code": "9",
            "commission_amount": 1000,
            "status": "pending",
        }])
        save_express_visit_requests([{
            "id": "v9",
            "partner_phone": ADVISOR,
            "owner_phone": OWNER,
            "land_code": "9",
            "status": "completed",
            "visit_outcome": "interested",
            "deal_decision": "approved",
        }])
    with client.session_transaction() as sess:
        sess["user_phone"] = ADVISOR
        sess["VINOR_IS_EXPRESS_PARTNER"] = True
    denied = client.post("/express/partner/requests/v9/deal-close")
    assert denied.status_code == 400
    assert "مالک فایل" in denied.get_json()["error"]
    assert seen == {}
    with client.session_transaction() as sess:
        sess["user_phone"] = OWNER
    closed = client.post("/express/partner/inbox-visits/v9/close_deal")
    assert closed.status_code == 302, closed.get_data(as_text=True)[:300]
    assert seen.get("owner") == OWNER


def test_close_before_approval_does_not_call_payout(monkeypatch):
    from app.express_partner.special_visit_inbox import commit_deal_after_listing

    def _payout(*_a, **_k):
        raise AssertionError("payout must wait for deal_decision=approved")

    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox._apply_special_deal_action",
        _payout,
    )
    row = {
        "id": "early",
        "status": "completed",
        "partner_phone": ADVISOR,
        "land_code": "9",
        "visit_outcome": "interested",
    }
    rows = [row]
    updated, err = commit_deal_after_listing(
        rows,
        row,
        decision="closed",
        actor_phone=ADVISOR,
        owner_phone=OWNER,
    )
    assert updated is None
    assert err == "invalid_decision"
    assert not row.get("deal_decision")


def test_locked_update_keeps_a_concurrent_disk_field(app, monkeypatch):
    from app.express_partner.visit_requests import locked_mutate_visit_requests
    from app.utils.storage import load_express_visit_requests, save_express_visit_requests

    with app.app_context():
        save_express_visit_requests([{
            "id": "v1",
            "partner_phone": ADVISOR,
            "status": "approved",
            "note_from_disk": "keep",
        }])
        stale = [{"id": "v1", "partner_phone": ADVISOR, "status": "pending"}]
        monkeypatch.setattr(
            "app.express_partner.routes.load_express_visit_requests",
            lambda *a, **k: stale,
        )

        def _mutate(rows):
            assert rows[0]["note_from_disk"] == "keep"
            rows[0]["status"] = "completed"
            return True

        locked_mutate_visit_requests(_mutate)
        stored = load_express_visit_requests()[0]
    assert stored["status"] == "completed"
    assert stored["note_from_disk"] == "keep"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-followup")
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


OTHER = "09124444000"
MARKETER = ADVISOR


def _people(extra=None):
    rows = [
        {"phone": MARKETER, "name": "بازاریاب", "status": "approved", "partner_tier": "partner"},
        {"phone": OWNER, "name": "مالک", "status": "approved", "partner_tier": "partner"},
        {"phone": OTHER, "name": "مالک دیگر", "status": "approved", "partner_tier": "partner"},
    ]
    if extra:
        rows.extend(extra)
    return rows


def _login(client, phone):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone
        sess["VINOR_IS_EXPRESS_PARTNER"] = True


def test_marketer_done_waits_for_the_listing_owner(app, client, monkeypatch):
    from app.utils.storage import load_express_visit_requests, save_ads, save_express_partners, save_express_visit_requests

    notes = []
    monkeypatch.setattr(
        "app.services.notifications.add_notification",
        lambda **kw: notes.append(kw) or {"ok": True},
    )
    monkeypatch.setattr(
        "app.express_partner.visit_sms.notify_partner_land_tx_sms",
        lambda **kw: notes.append(kw) or {"ok": True},
    )
    with app.app_context():
        save_express_partners(_people())
        save_ads([{
            "code": "9",
            "title": "فایل",
            "owner": OWNER,
            "is_express": True,
            "public": True,
        }])
        save_express_visit_requests([{
            "id": "m1",
            "partner_phone": MARKETER,
            "owner_phone": OWNER,
            "land_code": "9",
            "land_title": "فایل",
            "status": "approved",
        }])
    _login(client, MARKETER)
    done = client.post("/express/partner/requests/m1/complete", json={})
    assert done.status_code == 200
    assert done.get_json()["ok"] is True
    with app.app_context():
        row = load_express_visit_requests()[0]
    assert row["status"] == "done_pending"
    assert any(item.get("user_id") == OWNER for item in notes)
    assert any(item.get("partner_phone") == OWNER and item.get("event") == "visit_done_pending" for item in notes)

    _login(client, OWNER)
    confirmed = client.post("/express/partner/inbox-visits/m1/complete")
    assert confirmed.status_code == 302
    with app.app_context():
        row = load_express_visit_requests()[0]
    assert row["status"] == "completed"


def test_owner_deny_marks_no_show_and_tells_the_marketer(app, client, monkeypatch):
    from app.utils.storage import load_express_visit_requests, save_ads, save_express_partners, save_express_visit_requests

    sms = []
    monkeypatch.setattr(
        "app.express_partner.visit_sms.notify_partner_land_tx_sms",
        lambda **kw: sms.append(kw) or {"ok": True},
    )
    with app.app_context():
        save_express_partners(_people())
        save_ads([{"code": "9", "title": "فایل", "owner": OWNER, "is_express": True, "public": True}])
        save_express_visit_requests([{
            "id": "m2",
            "partner_phone": MARKETER,
            "owner_phone": OWNER,
            "land_code": "9",
            "status": "done_pending",
        }])
    _login(client, OWNER)
    denied = client.post(
        "/express/partner/inbox-visits/m2/no_show",
        data={"dispute_reason": "بازدید انجام نشده بود"},
    )
    assert denied.status_code == 302
    with app.app_context():
        row = load_express_visit_requests()[0]
    assert row["status"] == "disputed"
    assert row.get("dispute_reason")


def test_owner_who_marks_done_completes_immediately(app, client):
    from app.utils.storage import load_express_visit_requests, save_ads, save_express_partners, save_express_visit_requests

    with app.app_context():
        save_express_partners(_people())
        save_ads([{"code": "9", "title": "فایل", "owner": OWNER, "is_express": True, "public": True}])
        save_express_visit_requests([{
            "id": "m3",
            "partner_phone": MARKETER,
            "owner_phone": OWNER,
            "land_code": "9",
            "status": "approved",
        }])
    _login(client, OWNER)
    done = client.post("/express/partner/inbox-visits/m3/complete")
    assert done.status_code == 302
    with app.app_context():
        row = load_express_visit_requests()[0]
    assert row["status"] == "approved"


def test_normal_owner_starts_and_closes_and_others_cannot(app, client, monkeypatch):
    from app.utils.storage import (
        load_express_visit_requests,
        save_ads,
        save_express_assignments,
        save_express_commissions,
        save_express_partners,
        save_express_visit_requests,
    )

    paid = {}

    def _payout(*, deal_id, owner_phone):
        paid["owner"] = owner_phone
        return None, {"idempotent": False}

    monkeypatch.setattr("app.express_partner.deal_wallet.finalize_deal_payout", _payout)
    with app.app_context():
        save_express_partners(_people())
        save_ads([{"code": "9", "title": "فایل", "owner": OWNER, "is_express": True, "public": True}])
        save_express_assignments([{
            "id": 1,
            "land_code": "9",
            "partner_phone": MARKETER,
            "status": "active",
        }])
        save_express_commissions([{
            "id": 2,
            "commission_type": "deal",
            "partner_phone": MARKETER,
            "land_code": "9",
            "commission_amount": 1000,
            "status": "pending",
        }])
        save_express_visit_requests([{
            "id": "m4",
            "partner_phone": MARKETER,
            "owner_phone": OWNER,
            "land_code": "9",
            "status": "completed",
            "visit_outcome": "interested",
        }])
    _login(client, MARKETER)
    blocked = client.post("/express/partner/requests/m4/deal-confirm")
    assert blocked.status_code == 400
    assert "مالک فایل" in blocked.get_json()["error"]
    _login(client, OTHER)
    foreign = client.post("/express/partner/inbox-visits/m4/confirm_deal")
    assert foreign.status_code == 302
    with app.app_context():
        assert not load_express_visit_requests()[0].get("deal_decision")
    _login(client, OWNER)
    opened = client.post("/express/partner/inbox-visits/m4/confirm_deal")
    assert opened.status_code == 302
    with app.app_context():
        assert load_express_visit_requests()[0].get("deal_decision") == "approved"
    closed = client.post("/express/partner/inbox-visits/m4/close_deal")
    assert closed.status_code == 302
    assert paid.get("owner") == OWNER
    with app.app_context():
        assert load_express_visit_requests()[0].get("deal_decision") == "closed"


def test_requester_card_hides_deal_buttons():
    from app.express_partner.visit_requests import partner_request_feed_item

    card = partner_request_feed_item(
        {
            "id": "m5",
            "status": "completed",
            "visit_outcome": "interested",
            "partner_phone": MARKETER,
            "land_code": "9",
        },
        allow_attendance=True,
        allow_deal=False,
        allow_result=True,
    )
    assert card["can_confirm_deal"] is False
    assert card["can_close_deal"] is False
    assert card["can_reject_deal"] is False
