# -*- coding: utf-8 -*-
"""انتشار فروش بعد از ۳۰ روز با همان توقف دستی قطع می‌شود."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

OWNER = "09120000000"
SECRET = "unit-test-sale-window"


def _published(code, *, created_at, published_at=None, title="ملک منتشر"):
    extras = {
        "published_for_sale": True,
        "listed_by_owner": True,
        "owner_home": False,
        "public": True,
    }
    row = {
        "code": code,
        "title": title,
        "owner": OWNER,
        "source": "my_property_published",
        "is_express": True,
        "public": True,
        "owner_home": False,
        "ad_type": "express",
        "status": "approved",
        "express_status": "approved",
        "price_total": 1_000_000,
        "payment_method": "نقدی",
        "images": ["photo.jpg"],
        "created_at": created_at,
        "extras": extras,
    }
    if published_at:
        row["published_at"] = published_at
        extras["published_at"] = published_at
        extras["first_published_at"] = published_at
    return row


def _flags(land):
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    return {
        "is_express": land.get("is_express"),
        "public": land.get("public"),
        "source": land.get("source"),
        "owner_home": land.get("owner_home"),
        "published_for_sale": extras.get("published_for_sale"),
        "archived": land.get("archived") is True,
        "archived_reason": land.get("archived_reason") or "",
        "title": land.get("title"),
        "images": land.get("images"),
        "payment_method": land.get("payment_method"),
    }


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-sale-window")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_WEBHOOK_SECRET", SECRET)
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


def test_remaining_time_for_live_expired_and_stopped():
    from app.listings.sale_publish_window import SALE_PUBLISH_WINDOW, sale_publish_fields

    anchor = datetime(2026, 9, 1, 12, 0, 0)
    now = anchor + timedelta(days=10, seconds=5)
    live = _published("1", created_at="2020-01-01 00:00:00", published_at="2026-09-01T12:00:00Z")
    fields = sale_publish_fields(live, now=now)
    left = int((SALE_PUBLISH_WINDOW - timedelta(days=10, seconds=5)).total_seconds())
    assert fields["sale_publish_expires_at"] == "2026-10-01T12:00:00Z"
    assert fields["sale_publish_remaining_seconds"] == left
    assert fields["sale_publish_remaining_seconds"] > 0

    overdue = sale_publish_fields(live, now=anchor + timedelta(days=31))
    assert overdue["sale_publish_expires_at"] == "2026-10-01T12:00:00Z"
    assert overdue["sale_publish_remaining_seconds"] == 0

    stopped = _published("1", created_at="2026-09-01T12:00:00Z", published_at="2026-09-01T12:00:00Z")
    stopped["source"] = "my_property"
    stopped["is_express"] = False
    stopped["public"] = False
    stopped["extras"]["published_for_sale"] = False
    quiet = sale_publish_fields(stopped, now=now)
    assert quiet["sale_publish_expires_at"] is None
    assert quiet["sale_publish_remaining_seconds"] is None


def test_legacy_published_30_days_ago_stops_and_younger_legacy_stays(app):
    from app.listings.sale_publish_window import sweep_expired_sale_publishes
    from app.listings.service import archive_listing, get_listing, is_archived, is_published_for_sale
    from app.utils.public_listings import is_publicly_visible_listing
    from app.utils.storage import load_express_lands_cached, save_ads

    now = datetime(2026, 10, 19, 6, 0, 0)
    old_created = "2026-08-01 08:00:00"
    young_created = "2026-10-10 08:00:00"
    old = _published("40", created_at=old_created, title="قدیمی بدون مهر")
    young = _published("10", created_at=young_created, title="تازه بدون مهر")
    catalog = {
        "code": "77",
        "title": "فایل عادی اکسپرس",
        "owner": "09129999999",
        "source": "express",
        "is_express": True,
        "public": True,
        "created_at": "2020-01-01 00:00:00",
        "extras": {},
    }
    archived = _published("5", created_at=young_created, published_at="2026-10-12T00:00:00Z", title="بایگانی دستی")
    with app.app_context():
        save_ads([old, young, catalog, archived])
        archive_listing("5", phone=OWNER, reason="manual", require_owner=True)
        before = get_listing("5")
        stamp = before.get("archived_at")
        assert is_publicly_visible_listing(get_listing("40")) is False
        assert is_publicly_visible_listing(get_listing("10")) is True
        assert is_publicly_visible_listing(catalog) is True
        result = sweep_expired_sale_publishes(now=now)
        assert result["stopped"] == ["40"]
        assert "10" in result["kept"]
        assert "77" not in result["stopped"]
        stopped = get_listing("40")
        kept = get_listing("10")
        boxed = get_listing("5")
        assert get_listing("77")["source"] == "express"
        assert is_published_for_sale(stopped) is False
        assert stopped["is_express"] is False
        assert stopped["public"] is False
        assert stopped["source"] == "my_property"
        assert stopped["extras"]["published_for_sale"] is False
        assert stopped["title"] == "قدیمی بدون مهر"
        assert stopped["images"] == ["photo.jpg"]
        assert stopped["payment_method"] == "نقدی"
        assert is_archived(stopped) is True
        assert stopped["archived_reason"] == "inactive"
        assert is_published_for_sale(kept) is True
        assert is_archived(kept) is False
        assert kept.get("published_at") in (None, "")
        assert kept["sale_published_at"] == "2026-10-10T08:00:00Z"
        assert kept["extras"]["sale_published_at"] == "2026-10-10T08:00:00Z"
        assert boxed["archived_reason"] == "manual"
        assert boxed["archived_at"] == stamp
        assert boxed["title"] == "بایگانی دستی"
        assert all(str(row.get("code")) != "40" for row in load_express_lands_cached())
        again = sweep_expired_sale_publishes(now=now)
        assert again["stopped"] == []
        assert get_listing("40")["archived_at"] == stopped["archived_at"]


def test_dated_listing_under_30_days_is_untouched_and_past_30_matches_manual_stop(app):
    from app.express_partner.special_listings import unpublish_owner_home
    from app.listings.sale_publish_window import sweep_expired_sale_publishes
    from app.listings.service import get_listing
    from app.utils.storage import save_ads

    now = datetime(2026, 10, 19, 6, 0, 0)
    recent = (now - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (now - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    young = _published("2", created_at="2026-01-01 00:00:00", published_at=recent, title="زیر سی روز")
    old = _published("3", created_at="2026-01-01 00:00:00", published_at=stale, title="بالای سی روز")
    twin = _published("4", created_at="2026-01-01 00:00:00", published_at=stale, title="توقف دستی")
    with app.app_context():
        save_ads([young, old, twin])
        unpublish_owner_home(OWNER, land_code="4")
        result = sweep_expired_sale_publishes(now=now)
        assert result["stopped"] == ["3"]
        assert result["kept"] == ["2"]
        kept = get_listing("2")
        assert kept["published_at"] == recent
        assert kept["is_express"] is True
        assert kept["sale_published_at"] == recent
        auto = _flags(get_listing("3"))
        manual = _flags(get_listing("4"))
        auto.pop("title")
        manual.pop("title")
        assert auto == manual


def test_republish_resets_the_30_day_clock(app):
    from app.listings.sale_publish_window import sweep_expired_sale_publishes
    from app.listings.service import get_listing, publish_listing
    from app.utils.storage import save_ads

    now = datetime(2026, 10, 19, 6, 0, 0)
    stale = (now - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = _published("8", created_at="2026-01-01 00:00:00", published_at=stale)
    with app.app_context():
        save_ads([row])
        assert sweep_expired_sale_publishes(now=now)["stopped"] == ["8"]
        published, err, changed = publish_listing(
            OWNER,
            payment_method="نقدی",
            commission_pct=2,
            land_code="8",
        )
        assert err is None and changed is True
        stamp = published["sale_published_at"]
        assert stamp
        assert stamp != stale
        assert published["published_at"] == stamp
        assert published["extras"]["published_for_sale"] is True
        assert get_listing("8")["archived"] is False
        later = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        assert sweep_expired_sale_publishes(now=later + timedelta(days=29))["stopped"] == []
        assert get_listing("8")["is_express"] is True
        assert sweep_expired_sale_publishes(now=later + timedelta(days=30))["stopped"] == ["8"]


def test_owner_apis_expose_sale_publish_clock(client, app):
    from datetime import timezone

    from app.listings.sale_publish_window import sale_publish_fields
    from app.utils.storage import save_ads

    anchor = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    raw = "2026-10-01T00:00:00Z"
    row = _published("6", created_at="2026-09-01 00:00:00", published_at=raw, title="ساعت انتشار")
    with app.app_context():
        save_ads([row])
    with client.session_transaction() as sess:
        sess["user_phone"] = OWNER
    body = client.get("/express/partner/api/my-property/data").get_json()
    assert body["published_for_sale"] is True
    assert body["sale_publish_expires_at"] == "2026-10-31T00:00:00Z"
    assert body["sale_publish_remaining_seconds"] >= 0
    item = next(row for row in body["items"] if row["code"] == "6")
    assert item["sale_publish_expires_at"] == body["sale_publish_expires_at"]
    assert item["sale_publish_remaining_seconds"] == body["sale_publish_remaining_seconds"]
    listing = next(row for row in body["listings"] if row["code"] == "6")
    assert listing["sale_publish_remaining_seconds"] == item["sale_publish_remaining_seconds"]
    prop = body["property"]
    assert prop["sale_publish_expires_at"] == "2026-10-31T00:00:00Z"
    detail = client.get("/express/partner/api/lands/6/data").get_json()
    assert detail["sale_publish_expires_at"] == "2026-10-31T00:00:00Z"
    assert detail["sale_publish_remaining_seconds"] >= 0
    expected = sale_publish_fields(row, now=datetime.now(timezone.utc))
    assert abs(item["sale_publish_remaining_seconds"] - expected["sale_publish_remaining_seconds"]) <= 2

    stopped = client.post(
        "/express/partner/api/my-property/publish?published_for_sale=0",
        json={"code": "6", "published_for_sale": False, "unpublish": True},
    )
    assert stopped.status_code == 200
    archived = client.get("/express/partner/api/my-property/data?status=archived").get_json()
    card = next(row for row in archived["items"] if row["code"] == "6")
    assert card["published_for_sale"] is False
    assert card["sale_publish_expires_at"] is None
    assert card["sale_publish_remaining_seconds"] is None
    assert archived["sale_publish_expires_at"] is None
    assert archived["sale_publish_remaining_seconds"] is None


def test_sweep_endpoint_is_token_protected_and_idempotent(client, app):
    from app.utils.storage import save_ads

    nowish = datetime(2026, 10, 18, 0, 0, 0)
    row = _published(
        "11",
        created_at="2026-10-01 00:00:00",
        published_at=nowish.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with app.app_context():
        save_ads([row])
    denied = client.get("/healthz/sale-publish-sweep")
    assert denied.status_code == 401
    allowed = client.post(
        "/healthz/sale-publish-sweep",
        headers={"X-Vinor-Otp-Diag": SECRET},
    )
    assert allowed.status_code == 200
    body = allowed.get_json()
    assert body["ok"] is True
    assert body["stopped"] == []
    assert "11" in body["kept"]
    again = client.get(
        "/healthz/sale-publish-sweep",
        headers={"X-Vinor-Otp-Diag": SECRET},
    )
    assert again.get_json()["stopped"] == []
