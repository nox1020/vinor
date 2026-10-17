# -*- coding: utf-8 -*-
"""بایگانی آگهی و کارت پیگیری."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

OWNER = "09120000000"
REQUESTER = "09123333333"
OTHER = "09122222222"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-listing-archive")
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


def _publish(phone=OWNER, title="آگهی بایگانی"):
    from app.listings.service import create_listing, publish_listing

    created = create_listing(
        {"title": title, "city": "کرج", "price_total": 2_000_000},
        owner=phone,
    )
    code = str(created["code"])
    published, err, changed = publish_listing(
        phone, payment_method="نقدی", commission_pct=2, land_code=code,
    )
    assert err is None and changed
    return published


def _request(code, requester=REQUESTER):
    from app.express_partner.visit_requests import create_visit_request

    rows = []
    day = date.today() + timedelta(days=1)
    last = None
    for _ in range(21):
        rec, err = create_visit_request(
            rows,
            partner_phone=requester,
            partner_name="مشاور",
            land_code=code,
            land_title="آگهی بایگانی",
            visit_date=day.isoformat(),
            customer_first_name="علی",
            customer_last_name="رضایی",
            customer_phone="09120000099",
        )
        last = err
        if rec:
            return rows, rec
        if err not in ("weekday_not_allowed", "no_hours", "past_date"):
            break
        day += timedelta(days=1)
    raise AssertionError(last)


def _save_visit(rows):
    from app.utils.storage import save_express_visit_requests

    save_express_visit_requests(rows)


def _row(code):
    from app.listings.service import get_listing

    return get_listing(code)


def test_owner_archive_restore_filter_and_ownership(client, app):
    from app.express_partner.apk_native import listings_payload
    from app.listings.service import archive_listing, get_listing
    from app.utils.storage import save_ads

    with app.app_context():
        published = _publish()
        code = str(published["code"])
        phone_only = {
            "code": "81",
            "title": "فقط فیلد phone",
            "phone": OWNER,
            "source": "express",
            "is_express": True,
            "public": True,
            "price_total": 1,
            "created_at": "2026-02-01T00:00:00Z",
        }
        owner_only = {
            "code": "82",
            "title": "فقط owner_phone",
            "owner_phone": OWNER,
            "source": "express",
            "is_express": True,
            "public": True,
            "price_total": 1,
            "created_at": "2026-02-02T00:00:00Z",
        }
        save_ads([published, phone_only, owner_only])

    _login(client, OTHER)
    denied = client.post("/express/partner/api/my-property/archive", json={"code": code})
    assert denied.status_code == 403
    assert denied.get_json()["error_code"] == "forbidden"

    _login(client, OWNER)
    first = client.post("/express/partner/api/my-property/archive", json={"code": code})
    assert first.status_code == 200
    body = first.get_json()
    assert body["ok"] is True
    assert body["archived"] is True
    assert body["is_archived"] is True
    assert body["archived_reason"] == "manual"
    assert body["archived_at"]
    assert body["already"] is False
    stamp = body["archived_at"]

    again = client.post("/express/partner/api/my-property/archive", json={"code": code})
    assert again.status_code == 200
    assert again.get_json()["already"] is True
    assert again.get_json()["archived_at"] == stamp

    active = client.get("/express/partner/api/my-property/data").get_json()
    assert active["status"] == "active"
    assert all(item["code"] != code for item in active["items"])
    assert active["counts"]["archived"] >= 1
    archived = client.get("/express/partner/api/my-property/data?status=archived").get_json()
    assert archived["status"] == "archived"
    match = next(item for item in archived["items"] if item["code"] == code)
    assert match["archived"] is True
    assert match["is_archived"] is True
    assert match["archived_reason"] == "manual"
    assert match["archived_at"] == stamp

    restored = client.post("/express/partner/api/my-property/restore", json={"code": code})
    assert restored.status_code == 200
    back = restored.get_json()
    assert back["archived"] is False
    assert back["is_archived"] is False
    assert back["archived_at"] == ""
    assert back["archived_reason"] == ""
    assert back["already"] is False
    with app.app_context():
        row = get_listing(code)
        assert row.get("is_express") is True
        assert row.get("public") is True
    idle = client.post("/express/partner/api/my-property/restore", json={"code": code})
    assert idle.get_json()["already"] is True

    for extra in ("81", "82"):
        owned, err, changed = None, None, None
        with app.app_context():
            owned, err, changed = archive_listing(extra, phone=OWNER, require_owner=True)
        assert err is None and changed
        assert owned.get("archived") is True

    with app.app_context():
        payload = listings_payload(OWNER, status="active")
        assert all(item["code"] != "81" for item in payload["items"])
        archived_payload = listings_payload(OWNER, status="archived")
        assert archived_payload["status"] == "archived"
        assert archived_payload["counts"]["archived"] >= 2
        assert any(item["code"] == "81" and item["is_archived"] for item in archived_payload["items"])

    missing = client.post("/express/partner/api/my-property/archive", json={"code": "404"})
    assert missing.status_code == 404
    assert missing.get_json()["error_code"] == "not_found"
    client.post("/express/partner/api/my-property/archive", data={"code": code})
    form = client.post("/express/partner/api/my-property/archive", data={"code": code})
    assert form.status_code == 302
    assert "status=archived" in form.headers["Location"]

    with client.session_transaction() as sess:
        sess.pop("user_phone", None)
    guest = client.post("/express/partner/api/my-property/archive", json={"code": code})
    assert guest.status_code == 401


def test_auto_archive_reasons_and_restore_guard(client, app):
    from app.express_partner.routes import _mark_express_land_sold
    from app.listings.service import (
        get_listing,
        restore_listing,
        sweep_inactive_listings,
        update_listing,
    )
    from app.utils.public_listings import is_partner_assignment_land, is_publicly_visible_listing
    from app.utils.storage import load_express_lands_cached

    with app.app_context():
        from app.listings.service import create_listing
        from app.utils.storage import load_express_visit_requests

        draft_code = str(create_listing(
            {"title": "پیش‌نویس", "city": "کرج", "price_total": 1},
            owner=OWNER,
        )["code"])
        quiet = _publish(title="بدون بازدید")
        quiet_code = str(quiet["code"])
        visited = _publish(title="با بازدید")
        visit_code = str(visited["code"])
        live = _publish(title="برای توقف و انتشار دوباره")
        live_code = str(live["code"])
        rows, rec = _request(visit_code)
        _save_visit(rows)
        assert sweep_inactive_listings() == 0
        assert get_listing(draft_code).get("archived") is not True

        update_listing(quiet_code, {"expires_at": "2020-01-01T00:00:00Z"}, owner=OWNER)
        assert sweep_inactive_listings() == 1
        expired = get_listing(quiet_code)
        assert expired.get("archived") is True
        assert expired.get("archived_reason") == "inactive"

        _mark_express_land_sold(visit_code)
        sold = get_listing(visit_code)
        assert sold.get("express_status") == "sold"
        assert sold.get("archived") is True
        assert sold.get("archived_reason") == "closed"
        card = next(row for row in load_express_visit_requests() if row.get("id") == rec["id"])
        assert card.get("archived") is True
        assert card.get("archived_reason") == "closed"
        assert is_publicly_visible_listing(sold) is False
        assert is_partner_assignment_land(sold) is False
        assert all(str(row.get("code")) != visit_code for row in load_express_lands_cached() or [])

        restored, err, changed = restore_listing(visit_code, phone=OWNER)
        assert err is None and changed
        card = next(row for row in load_express_visit_requests() if row.get("id") == rec["id"])
        assert card.get("archived") is True
        restored_quiet, err, changed = restore_listing(quiet_code, phone=OWNER)
        assert err is None and changed
        assert sweep_inactive_listings() == 0
        assert get_listing(quiet_code).get("archived") is not True
        assert restored_quiet.get("is_express") is True

    _login(client, OWNER)
    stopped = client.post(
        "/express/partner/api/my-property/publish",
        json={"code": live_code, "unpublish": True},
    )
    assert stopped.status_code == 200
    with app.app_context():
        row = get_listing(live_code)
        assert row.get("archived") is True
        assert row.get("archived_reason") == "inactive"
        assert is_publicly_visible_listing(row) is False

    _login(client, OTHER)
    assert client.get(f"/express/partner/api/lands/{live_code}/data").status_code == 404
    _login(client, OWNER)
    assert client.get(f"/express/partner/api/lands/{live_code}/data").status_code == 200

    republished = client.post(
        "/express/partner/api/my-property/publish",
        json={"code": live_code, "payment_method": "نقدی", "commission_pct": "2"},
    )
    assert republished.status_code == 200
    shown = next(item for item in republished.get_json()["items"] if item["code"] == live_code)
    assert shown["published_for_sale"] is True
    assert shown["archived"] is False
    with app.app_context():
        visible = get_listing(live_code)
        assert is_publicly_visible_listing(visible) is True
        assert any(str(row.get("code")) == live_code for row in load_express_lands_cached() or [])

    manual = client.post("/express/partner/api/my-property/archive", json={"code": live_code})
    assert manual.get_json()["archived_reason"] == "manual"
    stayed = client.post(
        "/express/partner/api/my-property/publish",
        json={"code": live_code, "payment_method": "نقدی", "commission_pct": "2"},
    )
    assert stayed.status_code == 400
    assert stayed.get_json()["error_code"] == "already_published"
    active = client.get("/express/partner/api/my-property/data").get_json()
    assert all(item["code"] != live_code for item in active["items"])
    with app.app_context():
        assert get_listing(live_code).get("archived") is True


def test_owner_delete_archives_and_admin_delete_removes(client, app):
    from app.listings.service import get_listing
    from app.utils.storage import load_express_assignments, save_express_assignments

    with app.app_context():
        published = _publish()
        code = str(published["code"])
        save_express_assignments([
            {"id": 1, "partner_phone": REQUESTER, "land_code": code, "status": "active"},
        ])

    _login(client, OTHER)
    assert client.post("/express/partner/api/my-property/delete", json={"code": code}).status_code == 404
    _login(client, OWNER)
    deleted = client.post("/express/partner/api/my-property/delete", json={"code": code})
    assert deleted.status_code == 200
    body = deleted.get_json()
    assert body["ok"] is True
    assert body["deleted"] is False
    assert body["archived_reason"] == "manual"
    assert all(item["code"] != code for item in body["page_payload"]["items"])
    with app.app_context():
        assert get_listing(code).get("archived") is True
        assert any(str(row.get("land_code")) == code for row in load_express_assignments() or [])

    with client.session_transaction() as sess:
        sess.clear()
    guest = client.post(f"/admin/api/listings/{code}/delete")
    assert guest.status_code == 302
    assert "login" in guest.headers["Location"]

    with client.session_transaction() as sess:
        sess["logged_in"] = True
    removed = client.post(f"/admin/api/listings/{code}/delete")
    assert removed.status_code == 200
    assert removed.get_json()["deleted"] is True
    missing = client.post(f"/admin/api/listings/{code}/delete")
    assert missing.status_code == 404
    with app.app_context():
        assert get_listing(code) is None


def test_followup_cards_have_their_own_archive(client, app):
    from app.express_partner.apk_native import requests_payload
    from app.express_partner.routes import _build_partner_sales_pipeline
    from app.listings.service import archive_listing, get_listing, restore_listing
    from app.utils.storage import load_express_visit_requests, save_ads

    with app.app_context():
        published = _publish()
        code = str(published["code"])
        previous = dict(published)
        previous["extras"] = {"previous_code": "77"}
        save_ads([previous])
        rows, rec = _request("77")
        _save_visit(rows)
        vid = rec["id"]
        plain = {"phone": OWNER, "status": "approved", "partner_tier": "partner", "name": "مالک"}

    _login(client, OTHER)
    stranger = client.post(f"/express/partner/api/requests/{vid}/archive")
    assert stranger.status_code == 403
    assert stranger.get_json()["error_code"] == "forbidden"

    _login(client, REQUESTER)
    archived = client.post(f"/express/partner/api/requests/{vid}/archive")
    assert archived.status_code == 200
    card = archived.get_json()
    assert card["ok"] is True
    assert card["id"] == vid
    assert card["archived"] is True
    assert card["is_archived"] is True
    assert card["archived_reason"] == "manual"
    assert card["archived_at"]
    assert card["already"] is False
    repeat = client.post(f"/express/partner/api/requests/{vid}/archive")
    assert repeat.get_json()["already"] is True
    assert repeat.get_json()["archived_at"] == card["archived_at"]

    with app.app_context():
        owner_view = requests_payload(OWNER, plain, status="active")
        assert owner_view["archive_counts"]["archived"] == 1
        assert owner_view["cards"] == []
        hidden = requests_payload(OWNER, plain, status="archived")
        assert hidden["status"] == "archived"
        assert hidden["cards"][0]["id"] == vid
        assert hidden["cards"][0]["archived_reason"] == "manual"
        assert _build_partner_sales_pipeline(REQUESTER, plain)["cards"] == []

    restored = client.post(f"/express/partner/api/requests/{vid}/restore")
    assert restored.status_code == 200
    back = restored.get_json()
    assert back["archived"] is False
    assert back["listing_archived"] is False
    idle = client.post(f"/express/partner/api/requests/{vid}/restore")
    assert idle.get_json()["already"] is True

    with app.app_context():
        land, err, changed = archive_listing(code, phone=OWNER, require_owner=True)
        assert err is None and changed
        stored = next(row for row in load_express_visit_requests() if row.get("id") == vid)
        assert stored.get("archived") is True
        assert stored.get("archived_reason") == "manual"
        stamp = str(land.get("archived_at") or "")

    _login(client, OWNER)
    brought = client.post(f"/express/partner/api/requests/{vid}/restore")
    assert brought.status_code == 200
    assert brought.get_json()["archived"] is False
    assert brought.get_json()["listing_archived"] is True
    with app.app_context():
        from app.express_partner.visit_requests import sync_archived_listing_cards

        assert sync_archived_listing_cards(code, "manual", stamp) == 0
        stored = next(row for row in load_express_visit_requests() if row.get("id") == vid)
        assert stored.get("archived") is not True
        restore_listing(code, phone=OWNER)
        archive_listing(code, phone=OWNER, require_owner=True)
        stored = next(row for row in load_express_visit_requests() if row.get("id") == vid)
        assert stored.get("archived") is True
        assert str(stored.get("archived_at") or "") != stamp
        assert get_listing(code).get("archived") is True

    active = client.get("/express/partner/api/requests/data").get_json()
    assert active["status"] == "active"
    assert all(item["id"] != vid for item in active["cards"])
    archived_feed = client.get("/express/partner/api/requests/data?status=archived").get_json()
    assert archived_feed["archive_counts"]["archived"] >= 1
    assert any(item["id"] == vid and item["is_archived"] for item in archived_feed["cards"])

    form = client.post(f"/express/partner/api/requests/{vid}/restore", data={"ok": "1"})
    assert form.status_code == 302
    assert "status=active" in form.headers["Location"]
    missing = client.post("/express/partner/api/requests/missing-visit/archive")
    assert missing.status_code == 404

    page = client.get("/express/partner/my-property")
    assert page.status_code == 200
    assert "بایگانی".encode() in page.data
    follow = client.get("/express/partner/requests?status=archived")
    assert follow.status_code == 200
    assert "بازگرداندن به پیگیری".encode() in follow.data or "پیگیری بایگانی".encode() in follow.data
