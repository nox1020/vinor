# -*- coding: utf-8 -*-
"""«فروخته شد» از طرف مالک: مالکیت، تکرار، بلوکه، بازبینی ادمین، مسیر بازدید."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

OWNER = "09120000000"
MARKETER = "09123333333"
OTHER = "09122222222"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-owner-sold")
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


def _login(client, phone):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


def _publish(phone=OWNER):
    from app.listings.service import create_listing, publish_listing
    from app.utils.storage import load_express_commissions, save_express_commissions, save_express_partners

    save_express_partners([
        {"phone": OWNER, "name": "مالک", "status": "approved", "total_income": 0},
        {"phone": MARKETER, "name": "بازاریاب", "status": "approved", "total_income": 0},
        {"phone": OTHER, "name": "دیگری", "status": "approved", "total_income": 0},
    ])
    created = create_listing({"title": "ملک فروشی", "city": "کرج", "price_total": 2_000_000_000}, owner=phone)
    code = str(created["code"])
    funded = list(load_express_commissions() or [])
    funded.append({
        "id": len(funded) + 1, "commission_type": "manual_adjustment", "partner_phone": phone,
        "land_code": "manual", "commission_amount": 500_000_000, "status": "approved", "source": "test_fund",
    })
    save_express_commissions(funded)
    published, err, changed = publish_listing(phone, payment_method="نقدی", commission_pct=2, land_code=code)
    assert err is None and changed
    return code


def _completed_visit(code, partner=MARKETER):
    from app.express_partner.visit_requests import create_visit_request
    from app.utils.storage import save_express_visit_requests

    rows = []
    day = date.today() + timedelta(days=1)
    for _ in range(21):
        rec, err = create_visit_request(
            rows, partner_phone=partner, partner_name="بازاریاب", land_code=code,
            land_title="ملک فروشی", visit_date=day.isoformat(), customer_first_name="علی",
            customer_last_name="رضایی", customer_phone="09120000099",
        )
        if rec:
            rec["status"] = "completed"
            rec["visit_outcome"] = "interested"
            save_express_visit_requests(rows)
            return rec
        day += timedelta(days=1)
    raise AssertionError("no visit slot")


def _hold(code):
    from app.utils.storage import load_express_commissions

    rows = [r for r in load_express_commissions() or []
            if r.get("commission_type") == "escrow_hold" and str(r.get("land_code")) == str(code)]
    return rows[-1] if rows else None


def test_only_owner_sees_and_can_mark_sold(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    data = client.get("/express/partner/api/my-property/data").get_json()
    card = next(i for i in data["items"] if str(i["code"]) == code)
    assert card["can_mark_sold"] is True and card["sold"] is False

    _login(client, OTHER)
    assert client.get(f"/express/partner/api/my-property/sold-options?code={code}").status_code == 403
    resp = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "outside"})
    assert resp.status_code == 403
    assert resp.get_json()["error_code"] == "forbidden"
    assert client.get(f"/express/partner/my-property/{code}/sold").status_code == 403
    with app.app_context():
        from app.listings.service import get_listing
        assert get_listing(code).get("express_status") != "sold"
        assert _hold(code)["status"] == "held"


def test_outside_sale_without_visits_releases_hold_and_is_idempotent(client, app):
    with app.app_context():
        code = _publish()
        assert _hold(code)["status"] == "held"
    _login(client, OWNER)
    opts = client.get(f"/express/partner/api/my-property/sold-options?code={code}").get_json()
    assert opts["visits"] == [] and opts["review_required_if_outside"] is False

    bad = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "x"})
    assert bad.status_code == 400 and bad.get_json()["error_code"] == "invalid_channel"

    resp = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "outside"})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["sold"] is True and body["already"] is False and body["review_required"] is False
    assert body["archived"] is True and body["archived_reason"] == "closed"
    with app.app_context():
        from app.listings.service import get_listing
        land = get_listing(code)
        assert land["express_status"] == "sold"
        assert land["extras"]["sold_channel"] == "outside"
        assert _hold(code)["status"] == "released"
        assert _hold(code)["release_reason"] == "owner_sold_outside"

    again = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "outside"})
    assert again.status_code == 200 and again.get_json()["already"] is True
    data = client.get("/express/partner/api/my-property/data?status=archived").get_json()
    card = next(i for i in data["items"] if str(i["code"]) == code)
    assert card["sold"] is True and card["can_mark_sold"] is False


def test_outside_sale_after_completed_visit_goes_to_admin_review(client, app):
    with app.app_context():
        code = _publish()
        visit = _completed_visit(code)
    _login(client, OWNER)
    opts = client.get(f"/express/partner/api/my-property/sold-options?code={code}").get_json()
    assert [v["visit_id"] for v in opts["visits"]] == [visit["id"]]
    assert opts["review_required_if_outside"] is True
    assert "بررسی" in opts["outside_confirm_message"]

    resp = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "outside"})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["review_required"] is True and body["hold_released"] is False
    with app.app_context():
        from app.express_partner.commission_escrow import release_publish_hold, resolve_review_release, review_rows
        from app.listings.service import archive_listing

        hold = _hold(code)
        assert hold["status"] == "held" and hold["review_required"] is True
        assert hold["review_visit_ids"] == [visit["id"]]
        # automatic paths must not release a hold under review
        assert release_publish_hold(code, reason="archived") is False
        archive_listing(code, reason="closed", require_owner=False)
        assert _hold(code)["status"] == "held"
        assert [r["land_code"] for r in review_rows()] == [code]
        assert resolve_review_release(code, admin="admin") is True
        assert _hold(code)["status"] == "released"
        assert review_rows() == []


def test_vinor_sale_requires_a_completed_visit_of_this_listing(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    resp = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "vinor"})
    assert resp.status_code == 400 and resp.get_json()["error_code"] == "visit_required"
    resp = client.post("/express/partner/api/my-property/sold",
                       json={"code": code, "channel": "vinor", "visit_id": "nope"})
    assert resp.status_code == 404 and resp.get_json()["error_code"] == "visit_not_found"


def test_vinor_sale_runs_existing_deal_flow_and_pays_from_hold(client, app, monkeypatch):
    monkeypatch.setattr("app.express_partner.special_visit_inbox.inject_visit_deal_chat", lambda *_a, **_k: None)
    with app.app_context():
        code = _publish()
        visit = _completed_visit(code)
        from app.utils.storage import save_express_assignments
        save_express_assignments([{"land_code": code, "partner_phone": MARKETER, "status": "active"}])
        held = int(_hold(code)["commission_amount"])
        assert held > 0
    _login(client, OWNER)
    resp = client.post("/express/partner/api/my-property/sold",
                       json={"code": code, "channel": "vinor", "visit_id": visit["id"]})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["sold"] is True and body["channel"] == "vinor"
    with app.app_context():
        from app.listings.service import get_listing
        from app.utils.storage import load_express_commissions, load_express_visit_requests

        land = get_listing(code)
        assert land["express_status"] == "sold"
        assert land["extras"]["sold_visit_id"] == visit["id"]
        deals = [r for r in load_express_commissions() if r.get("commission_type") == "deal"]
        assert len(deals) == 1 and deals[0]["partner_phone"] == MARKETER
        assert deals[0]["status"] == "approved" and deals[0]["payout_settled"] is True
        assert _hold(code)["status"] == "settled"
        row = next(r for r in load_express_visit_requests() if r.get("id") == visit["id"])
        assert row.get("deal_decision") == "closed"
    again = client.post("/express/partner/api/my-property/sold",
                        json={"code": code, "channel": "vinor", "visit_id": visit["id"]})
    assert again.status_code == 200 and again.get_json()["already"] is True
    with app.app_context():
        from app.utils.storage import load_express_commissions
        assert len([r for r in load_express_commissions() if r.get("commission_type") == "deal"]) == 1


def test_web_page_and_form_post(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    page = client.get("/express/partner/my-property")
    assert page.status_code == 200
    assert f"/express/partner/my-property/{code}/sold" in page.get_data(as_text=True)
    sold_page = client.get(f"/express/partner/my-property/{code}/sold")
    html = sold_page.get_data(as_text=True)
    assert sold_page.status_code == 200 and "خودم بیرون از وینور فروختم" in html and "confirm" in html
    resp = client.post("/express/partner/api/my-property/sold",
                       data={"code": code, "channel": "outside", "visit_id": ""})
    assert resp.status_code == 302
    with app.app_context():
        from app.listings.service import get_listing
        assert get_listing(code)["express_status"] == "sold"


def test_admin_review_page_and_deal_start(client, app, monkeypatch):
    monkeypatch.setattr("app.express_partner.special_visit_inbox._notify_started_deal", lambda *_a, **_k: None)
    with app.app_context():
        code = _publish()
        visit = _completed_visit(code)
        from app.utils.storage import save_express_assignments
        save_express_assignments([{"land_code": code, "partner_phone": MARKETER, "status": "active"}])
    _login(client, OWNER)
    assert client.post("/express/partner/api/my-property/sold",
                       json={"code": code, "channel": "outside"}).status_code == 200
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    page = client.get("/admin/express/commissions/escrow-review")
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and code in html and MARKETER in html
    resp = client.post(f"/admin/express/commissions/escrow-review/{code}/deal", data={"visit_id": visit["id"]})
    assert resp.status_code == 302
    with app.app_context():
        from app.express_partner.commission_escrow import review_rows
        from app.utils.storage import load_express_commissions

        deals = [r for r in load_express_commissions() if r.get("commission_type") == "deal"]
        assert len(deals) == 1 and deals[0]["status"] == "pending" and deals[0]["partner_phone"] == MARKETER
        hold = _hold(code)
        assert hold["status"] == "held" and hold["review_resolution"] == "deal_started"
        assert review_rows() == []
