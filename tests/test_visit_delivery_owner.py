# -*- coding: utf-8 -*-
"""بازدید یک آگهی فقط به مالک همان آگهی می‌رسد."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

OWNER_A = "09121000001"
OWNER_B = "09121000002"
THIRD = "09121000003"
BOOKER = "09121000004"
ADVISOR = "09121000014"
BUYER = "09121000015"
CODE_A = "5101"
CODE_B = "5102"
CODE_PREFIX = "510"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-visit-delivery")
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
    sms_sent: list[str] = []

    def _fake_sms(mobile, message="", line_number=None, record_history=False, **kwargs):
        sms_sent.append(str(mobile or ""))
        return {"ok": True, "status": 200, "body": {}}

    pushes: list[str] = []

    def _fake_push(user_id, title="", body="", url="", **kwargs):
        pushes.append(str(user_id or ""))

    monkeypatch.setattr("app.services.sms.send_sms_direct", _fake_sms)
    monkeypatch.setattr("app.express_partner.visit_sms.send_sms_direct", _fake_sms)
    monkeypatch.setattr("app.express_partner.admin_action_sms.send_sms_direct", _fake_sms)
    monkeypatch.setattr("app.services.fcm_push.send_fcm_to_user_background", _fake_push)
    import app.express_partner.special_visit_inbox as inbox
    import app.utils.storage as storage

    monkeypatch.setattr(inbox, "load_express_partners", storage.load_express_partners)
    monkeypatch.setattr(inbox, "save_express_partners", storage.save_express_partners)
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    application.sms_sent = sms_sent
    application.pushes = pushes
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _plus(phone, name):
    return {
        "phone": phone,
        "name": name,
        "status": "approved",
        "partner_tier": "special",
        "plus_expires_at": "2099-01-01T00:00:00Z",
    }


def _partner(phone, name):
    return {"phone": phone, "name": name, "status": "approved", "partner_tier": "partner"}


def _land(code, owner, *, previous=""):
    extras = {}
    if previous:
        extras["previous_code"] = previous
    return {
        "code": code,
        "title": f"آگهی {code}",
        "owner": owner,
        "is_express": True,
        "public": True,
        "source": "express",
        "price_total": 2_000_000,
        "extras": extras,
    }


def _seed(app, *, owner_a=OWNER_A):
    from app.utils.storage import save_ads, save_express_partners

    with app.app_context():
        save_express_partners([
            _plus(OWNER_A, "مالک الف"),
            _plus(OWNER_B, "مالک ب"),
            _partner(THIRD, "کاربر سوم"),
            _partner(BOOKER, "درخواست‌کننده"),
        ])
        save_ads([
            _land(CODE_A, owner_a),
            _land(CODE_B, OWNER_B, previous=CODE_A),
            _land(CODE_PREFIX, OWNER_B),
        ])


def _book(app, code=CODE_A, *, plus_phone=""):
    from app.express_partner.visit_requests import submit_visit_request

    day = date.today() + timedelta(days=1)
    last = None
    with app.app_context():
        for _ in range(21):
            rec, err = submit_visit_request(
                partner_phone=BOOKER,
                partner_name="درخواست‌کننده",
                land_code=code,
                land_title=f"آگهی {code}",
                visit_date=day.isoformat(),
                customer_first_name="علی",
                customer_last_name="رضایی",
                customer_phone="09120000099",
                require_customer=False,
                plus_user_phone=plus_phone,
                plus_user_name="مالک ب" if plus_phone else "",
            )
            last = err
            if rec:
                return rec
            if err not in ("weekday_not_allowed", "no_hours", "past_date"):
                break
            day += timedelta(days=1)
    raise AssertionError(last or "visit was not created")


def _login(client, phone):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


def _cards(client, phone):
    _login(client, phone)
    payload = client.get("/express/partner/api/requests/data").get_json()
    return list(payload.get("cards") or [])


def _incoming_ids(client, phone):
    return [
        str(card.get("id") or "")
        for card in _cards(client, phone)
        if card.get("direction") == "incoming"
    ]


def _notify_ids(app, phone):
    from app.services.notifications import get_user_notifications

    with app.app_context():
        rows = get_user_notifications(phone) or []
    return [str(row.get("user_id") or phone) for row in rows if row.get("type") == "visit" or row.get("title")]


def test_listing_visit_reaches_only_that_owner(app, client):
    _seed(app, owner_a="989121000001")
    rec = _book(app, CODE_A, plus_phone=OWNER_B)
    assert rec.get("owner_phone") == OWNER_A
    assert rec.get("plus_user_phone") in ("", OWNER_A)

    assert _incoming_ids(client, OWNER_A) == [rec["id"]]
    assert _incoming_ids(client, OWNER_B) == []
    assert _incoming_ids(client, THIRD) == []
    booker = _cards(client, BOOKER)
    assert [card["id"] for card in booker if card.get("direction") == "incoming"] == []
    assert [card["id"] for card in booker if card.get("direction") == "outgoing"] == [rec["id"]]

    assert _notify_ids(app, OWNER_A)
    assert _notify_ids(app, OWNER_B) == []
    assert _notify_ids(app, THIRD) == []


def test_selected_plus_does_not_replace_a_non_plus_listing_owner(app, client):
    from app.utils.storage import save_express_partners

    _seed(app)
    with app.app_context():
        save_express_partners([
            _partner(OWNER_A, "مالک الف"),
            _plus(OWNER_B, "مالک ب"),
            _partner(THIRD, "کاربر سوم"),
            _partner(BOOKER, "درخواست‌کننده"),
        ])
    rec = _book(app, CODE_A, plus_phone=OWNER_B)
    assert rec.get("owner_phone") == OWNER_A
    assert rec.get("plus_user_phone") in ("", None, OWNER_A)
    assert _incoming_ids(client, OWNER_A) == [rec["id"]]
    assert _incoming_ids(client, OWNER_B) == []
    assert _incoming_ids(client, THIRD) == []
    assert _notify_ids(app, OWNER_A)
    assert _notify_ids(app, OWNER_B) == []
    assert _notify_ids(app, THIRD) == []


def test_stored_plus_phone_and_empty_stamp_do_not_leak(app, client):
    from app.utils.storage import save_express_visit_requests

    _seed(app)
    with app.app_context():
        save_express_visit_requests([
            {
                "id": "stamped-wrong",
                "partner_phone": BOOKER,
                "partner_name": "درخواست‌کننده",
                "land_code": CODE_A,
                "land_title": "آگهی الف",
                "status": "approved",
                "owner_phone": OWNER_B,
                "plus_user_phone": OWNER_B,
                "customer_phone": "09120000081",
                "visit_date": "2026-11-02",
                "created_at": "2026-10-01T00:00:00Z",
                "updated_at": "2026-10-01T00:00:00Z",
            },
            {
                "id": "empty-phones",
                "partner_phone": BOOKER,
                "land_code": CODE_A,
                "status": "approved",
                "owner_phone": "",
                "plus_user_phone": "",
                "customer_phone": "09120000082",
                "visit_date": "2026-11-03",
                "created_at": "2026-10-02T00:00:00Z",
                "updated_at": "2026-10-02T00:00:00Z",
            },
            {
                "id": "blank-calendar",
                "partner_phone": BOOKER,
                "land_code": "",
                "status": "approved",
                "owner_phone": None,
                "plus_user_phone": None,
                "visit_date": "2026-11-04",
                "created_at": "2026-10-03T00:00:00Z",
                "updated_at": "2026-10-03T00:00:00Z",
            },
        ])

    assert set(_incoming_ids(client, OWNER_A)) == {"empty-phones", "stamped-wrong"}
    assert _incoming_ids(client, OWNER_B) == []
    assert _incoming_ids(client, THIRD) == []
    from app.express_partner.special_visit_inbox import visits_for_listing_owner

    with app.app_context():
        assert visits_for_listing_owner("") == []
        assert visits_for_listing_owner(None) == []


def test_calendar_without_a_listing_still_reaches_the_selected_plus(app, client):
    _seed(app)
    rec = _book(app, "", plus_phone=OWNER_B)
    assert _incoming_ids(client, OWNER_B) == [rec["id"]]
    assert _incoming_ids(client, OWNER_A) == []
    assert _incoming_ids(client, THIRD) == []
    assert _notify_ids(app, OWNER_B)
    assert _notify_ids(app, OWNER_A) == []
    assert _notify_ids(app, THIRD) == []


def test_schedule_sms_and_admin_sms_use_the_listing_owner(app, monkeypatch):
    _seed(app, owner_a="989121000001")
    sms = []

    def _capture_schedule(**kwargs):
        sms.append(str(kwargs.get("to_phone") or ""))
        return {"ok": True, "skipped": False, "error": None}

    monkeypatch.setattr(
        "app.express_partner.routes._send_visit_schedule_sms_to",
        _capture_schedule,
    )
    from app.express_partner.routes import _send_visit_schedule_partner_sms

    with app.app_context():
        _send_visit_schedule_partner_sms(
            partner_phone=BOOKER,
            partner_name="درخواست‌کننده",
            plus_user_phone=OWNER_B,
            plus_user_name="مالک ب",
            land_code=CODE_A,
        )
    assert BOOKER in sms
    assert OWNER_A in sms
    assert OWNER_B not in sms
    assert THIRD not in sms

    admin = []

    def _capture_direct(mobile, message, line_number=None, record_history=False):
        admin.append(str(mobile))
        return {"ok": True, "status": 200, "body": {}}

    monkeypatch.setattr(
        "app.express_partner.admin_action_sms.send_sms_direct",
        _capture_direct,
    )
    from app.express_partner.admin_action_sms import notify_admin_pending_action

    with app.app_context():
        notify_admin_pending_action(
            "visit",
            land_code=CODE_A,
            partner_phone=BOOKER,
            partner_name="درخواست‌کننده",
        )
    assert OWNER_A in admin
    assert OWNER_B not in admin
    assert THIRD not in admin
    assert BOOKER not in admin


def _post_listing_visit(client, phone, **fields):
    day = date.today() + timedelta(days=1)
    last = None
    for _ in range(21):
        _login(client, phone)
        response = client.post(
            f"/express/partner/visit-requests/{CODE_A}",
            data={"visit_date": day.isoformat(), **fields},
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        body = response.get_json(silent=True) or {}
        if response.status_code == 200 and body.get("success"):
            return body
        last = (response.status_code, body)
        message = str(body.get("message") or "")
        if "روز" not in message and "ساعت" not in message and "گذشته" not in message:
            break
        day += timedelta(days=1)
    raise AssertionError(last)


def _row_for(app, phone):
    from app.utils.storage import load_express_visit_requests

    with app.app_context():
        rows = load_express_visit_requests() or []
    return next(row for row in rows if str(row.get("partner_phone") or "") == phone)


def _visit_alerts(app, phone):
    from app.services.notifications import get_user_notifications

    with app.app_context():
        rows = get_user_notifications(phone) or []
    return [row for row in rows if str(row.get("type") or "") == "visit"]


def test_advisor_and_buyer_bookings_reach_only_the_listing_owner(app, client):
    """مشاور و خریدار عادی هر دو فقط روی پیگیری مالک، به‌اضافهٔ کارت ارسالی خودشان."""
    from app.services.sms import normalize_iran_mobile
    from app.utils.storage import load_express_partners, save_express_partners

    _seed(app)
    with app.app_context():
        partners = list(load_express_partners() or [])
        partners.extend([
            _partner(ADVISOR, "سارا کریمی"),
            {"phone": BUYER, "name": "علی رضایی", "status": "pending"},
        ])
        save_express_partners(partners)
    app.sms_sent.clear()
    app.pushes.clear()

    advisor_body = _post_listing_visit(
        client,
        ADVISOR,
        customer_first_name="نگار",
        customer_last_name="احمدی",
        customer_phone="09125556677",
    )
    buyer_body = _post_listing_visit(client, BUYER)
    assert advisor_body["success"] is True
    assert buyer_body["success"] is True

    advisor_row = _row_for(app, ADVISOR)
    buyer_row = _row_for(app, BUYER)
    assert advisor_row["owner_phone"] == OWNER_A
    assert buyer_row["owner_phone"] == OWNER_A
    assert advisor_row.get("plus_user_phone") in ("", None, OWNER_A)
    assert buyer_row.get("plus_user_phone") in ("", None, OWNER_A)
    assert advisor_row["customer_name"] == "نگار احمدی"
    assert buyer_row["customer_name"] == "علی رضایی"
    assert buyer_row["customer_phone"] == BUYER

    owner_in = set(_incoming_ids(client, OWNER_A))
    assert owner_in == {advisor_row["id"], buyer_row["id"]}
    assert _incoming_ids(client, OWNER_B) == []
    assert _incoming_ids(client, THIRD) == []

    advisor_cards = _cards(client, ADVISOR)
    buyer_cards = _cards(client, BUYER)
    assert [card["id"] for card in advisor_cards if card.get("direction") == "outgoing"] == [advisor_row["id"]]
    assert [card["id"] for card in advisor_cards if card.get("direction") == "incoming"] == []
    assert [card["id"] for card in buyer_cards if card.get("direction") == "outgoing"] == [buyer_row["id"]]
    assert [card["id"] for card in buyer_cards if card.get("direction") == "incoming"] == []
    assert advisor_row["id"] not in {card["id"] for card in buyer_cards}
    assert buyer_row["id"] not in {card["id"] for card in advisor_cards}

    assert _visit_alerts(app, OWNER_A)
    assert _visit_alerts(app, OWNER_B) == []
    assert _visit_alerts(app, THIRD) == []
    assert _visit_alerts(app, ADVISOR) == []
    assert _visit_alerts(app, BUYER) == []

    sms = {normalize_iran_mobile(phone) or phone for phone in app.sms_sent}
    pushes = {normalize_iran_mobile(phone) or phone for phone in app.pushes}
    assert OWNER_B not in sms
    assert THIRD not in sms
    assert OWNER_B not in pushes
    assert THIRD not in pushes
    assert ADVISOR not in pushes
    assert BUYER not in pushes
    assert pushes <= {OWNER_A}
    assert OWNER_A in pushes
