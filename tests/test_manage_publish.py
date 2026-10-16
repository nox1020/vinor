# -*- coding: utf-8 -*-
"""توقف انتشار، جزئیات مالک، و حذف ملک من."""
from __future__ import annotations

import pytest

OWNER = "09120000000"
PARTNER = "09121111111"
OTHER = "09122222222"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-manage-publish")
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


def _login(client, phone: str) -> None:
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


def _logout(client) -> None:
    with client.session_transaction() as sess:
        sess.pop("user_phone", None)


def _private(code="4", owner=OWNER):
    return {
        "code": code,
        "title": "ملک من برای تست انتشار",
        "owner": owner,
        "source": "my_property",
        "is_express": False,
        "public": False,
        "owner_home": True,
        "price_total": 1_000_000,
        "created_at": "2026-01-01T00:00:00Z",
        "extras": {
            "published_for_sale": False,
            "listed_by_owner": True,
            "owner_home": True,
        },
    }


def _public(code="9"):
    return {
        "code": code,
        "title": "زمین عمومی همکاران",
        "owner": "09129999999",
        "source": "express",
        "is_express": True,
        "public": True,
        "created_at": "2026-01-02T00:00:00Z",
        "extras": {},
    }


def _seed(app):
    from app.utils.storage import save_ads, save_express_partners

    with app.app_context():
        save_express_partners([
            {"phone": PARTNER, "status": "approved", "name": "الف"},
            {"phone": OTHER, "status": "approved", "name": "ب"},
        ])
        save_ads([_private(), _public()])


def _codes(lands):
    return [str(item.get("code") or "") for item in lands]


def test_publish_send_all_then_unpublish_leaves_partner_dashboard(app):
    from app.ai.agent_tools import _active_assignment_land_codes
    from app.ai.context import _assigned_lands
    from app.express_partner.routes import _build_partner_dashboard_lands
    from app.express_partner.special_listings import publish_owner_home, unpublish_owner_home
    from app.utils.storage import load_express_assignments, save_express_assignments

    _seed(app)
    with app.test_request_context():
        rec, err = publish_owner_home(
            OWNER,
            payment_method="نقدی",
            commission_pct="2",
            send_all=True,
            land_code="4",
        )
        assert err is None
        assert str((rec or {}).get("code")) == "4"
        listed, _expired = _build_partner_dashboard_lands(PARTNER, True)
        assert "4" in _codes(listed)

        rows = load_express_assignments() or []
        assert any(str(row.get("land_code")) == "4" for row in rows)
        for row in rows:
            if str(row.get("partner_phone")) == PARTNER and str(row.get("land_code")) == "4":
                row["status"] = "in_transaction"
            if str(row.get("partner_phone")) == OTHER and str(row.get("land_code")) == "4":
                row["status"] = "sold"
        rows.append({
            "id": 99,
            "partner_phone": PARTNER,
            "land_code": "4",
            "status": "active",
            "commission_pct": 2,
        })
        save_express_assignments(rows)

        _rec, stop_err = unpublish_owner_home(OWNER, land_code="4")
        assert stop_err is None
        after = load_express_assignments() or []
        by_phone = {
            (str(row.get("partner_phone")), str(row.get("status") or "")): row
            for row in after
            if str(row.get("land_code")) == "4"
        }
        assert by_phone[(PARTNER, "in_transaction")]["status"] == "in_transaction"
        assert by_phone[(OTHER, "sold")]["status"] == "sold"
        assert by_phone[(PARTNER, "revoked")]["status"] == "revoked"
        assert all(str(row.get("status")) != "active" for row in after if str(row.get("land_code")) == "4")

        for phone in (PARTNER, OTHER):
            dashboard, _expired = _build_partner_dashboard_lands(phone, True)
            assert "4" not in _codes(dashboard)
            assert "9" in _codes(dashboard)
            assigned = _assigned_lands(phone)
            assert "4" not in _codes(assigned)
        assert "4" not in _active_assignment_land_codes(PARTNER)
        from app.express_partner.routes import _express_land_in_catalog, _lands_for_favorite_codes

        favorites = _lands_for_favorite_codes(["4", "9"], PARTNER)
        assert "4" not in _codes(favorites)
        assert "9" in _codes(favorites)
        assert _express_land_in_catalog("4") is False
        assert _express_land_in_catalog("9") is True

        again, again_err = publish_owner_home(
            OWNER,
            payment_method="نقدی",
            commission_pct="2",
            send_all=True,
            land_code="4",
        )
        assert again_err is None
        assert str((again or {}).get("code")) == "4"
        relisted, _expired = _build_partner_dashboard_lands(PARTNER, True)
        assert "4" in _codes(relisted)
        restored = load_express_assignments() or []
        statuses = {
            str(row.get("partner_phone")): str(row.get("status") or "")
            for row in restored
            if str(row.get("land_code")) == "4" and str(row.get("status")) != "in_transaction"
        }
        assert statuses[PARTNER] == "active"
        assert any(
            str(row.get("partner_phone")) == PARTNER and str(row.get("status")) == "in_transaction"
            for row in restored
            if str(row.get("land_code")) == "4"
        )
        assert _express_land_in_catalog("4") is True


def test_private_land_data_is_owner_only(client, app):
    _seed(app)
    _login(client, OWNER)
    owner = client.get("/express/partner/api/lands/4/data")
    assert owner.status_code == 200
    body = owner.get_json()
    assert body["ok"] is False
    assert body["published_for_sale"] is False
    assert body["can_publish"] is True

    _login(client, OTHER)
    other = client.get("/express/partner/api/lands/4/data")
    assert other.status_code == 404
    assert other.get_json()["error_code"] == "not_found"
    assert other.get_json()["ok"] is False

    _logout(client)
    guest = client.get("/express/partner/api/lands/4/data")
    assert guest.status_code == 404
    assert guest.get_json()["error_code"] == "not_found"


def test_delete_removes_owner_rows_assignments_and_returns_page(client, app):
    from app.utils.storage import load_ads, load_express_assignments, save_express_assignments

    _seed(app)
    with app.app_context():
        save_express_assignments([
            {"id": 1, "partner_phone": PARTNER, "land_code": "4", "status": "active"},
            {"id": 2, "partner_phone": OTHER, "land_code": "9", "status": "active"},
            {"id": 3, "partner_phone": OWNER, "land_code": "4", "status": "in_transaction"},
        ])

    _login(client, OTHER)
    denied = client.post("/express/partner/api/my-property/delete", json={"code": "4"})
    assert denied.status_code == 404
    with app.app_context():
        assert any(str(row.get("code")) == "4" for row in load_ads() or [])

    _login(client, OWNER)
    gone = client.post("/express/partner/api/my-property/delete", json={"code": "4"})
    assert gone.status_code == 200
    body = gone.get_json()
    assert body["ok"] is True
    assert body["code"] == "4"
    assert body["message"]
    page = body["page_payload"]
    assert all(str(item.get("code")) != "4" for item in page["items"])
    with app.app_context():
        ads = load_ads() or []
        assert all(str(row.get("code")) != "4" for row in ads)
        assert any(str(row.get("code")) == "9" for row in ads)
        left = load_express_assignments() or []
        assert all(
            str(row.get("status")) in ("in_transaction", "sold")
            for row in left
            if str(row.get("land_code")) == "4"
        )
        assert any(
            str(row.get("land_code")) == "4" and str(row.get("status")) == "in_transaction"
            for row in left
        )
        assert any(str(row.get("land_code")) == "9" for row in left)

    missing = client.post("/express/partner/api/my-property/delete", json={"code": "404"})
    assert missing.status_code == 404
    assert missing.get_json()["error_code"] == "not_found"

    _logout(client)
    guest = client.post("/express/partner/api/my-property/delete", json={"code": "9"})
    assert guest.status_code == 401


def test_api_stops_regular_listing_and_owner_can_republish(client, app):
    from app.utils.storage import load_ads, save_ads
    from app.express_partner.my_property import property_cards

    ad = _public("9")
    ad["owner"] = OWNER
    ad["payment_method"] = "نقدی"
    ad["price_total"] = 1_000_000
    with app.app_context():
        save_ads([ad])
        assert property_cards(OWNER)[0]["published_for_sale"] is True
    _login(client, OTHER)
    denied = client.post("/express/partner/api/my-property/publish?published_for_sale=0",
                         json={"code": "9", "unpublish": True})
    assert denied.status_code == 400
    with app.app_context():
        assert load_ads()[0]["is_express"] is True
    _login(client, OWNER)
    response = client.post("/express/partner/api/my-property/publish?published_for_sale=0",
                           json={"code": "9", "published_for_sale": False, "unpublish": True})
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["items"][0]["published_for_sale"] is False
    assert client.get("/express/partner/api/lands/9/data").get_json()["published_for_sale"] is False
    _logout(client)
    assert client.get("/express/partner/api/lands/9/data").status_code == 404
    _login(client, OWNER)
    published = client.post("/express/partner/api/my-property/publish",
                            json={"code": "9", "payment_method": "نقدی", "commission_pct": "2"})
    assert published.status_code == 200
    assert published.get_json()["items"][0]["published_for_sale"] is True
