# -*- coding: utf-8 -*-
"""Public listing JSON must not include owner phones or contact numbers."""
from __future__ import annotations

import json

import pytest

OWNER = "09120000099"
CONTACT = "09121110099"
NATIONAL_ID = "0081234567"
LAND = {
    "id": "L9",
    "code": "L9",
    "title": "خانه تست",
    "price_total": 2500000000,
    "city": "گرمابسرد",
    "location": "دشت",
    "category": "خانه",
    "size": 120,
    "image_url": "/uploads/cover.jpg",
    "public": True,
    "source": "my_property_published",
    "is_express": True,
    "ad_type": "express",
    "badge_label": "منتشرشده",
    "owner_home": False,
    "published_for_sale": True,
    "listed_by_owner": True,
    "listed_by_special": False,
    "previous_code": "L8",
    "status": "approved",
    "express_status": "approved",
    "images": ["/uploads/cover.jpg"],
    "owner_phone": OWNER,
    "vinor_contact": CONTACT,
    "owner_name": "مالک خصوصی",
    "extras": {
        "previous_code": "L8",
        "published_for_sale": True,
        "listed_by_owner": True,
        "owner_home": False,
        "public": True,
        "listed_by_special": False,
        "owner_phone": OWNER,
        "vinor_contact": CONTACT,
        "notes": "یادداشت خصوصی",
        "owner_name": "مالک خصوصی",
        "national_id": NATIONAL_ID,
        "express_commission_pct": 2,
    },
    "created_at": "2026-11-01T00:00:00Z",
}

APP_FIELDS = (
    "id",
    "code",
    "image_url",
    "public",
    "source",
    "is_express",
    "ad_type",
    "badge_label",
    "owner_home",
    "published_for_sale",
    "listed_by_owner",
    "listed_by_special",
    "previous_code",
    "status",
    "express_status",
)
SAFE_EXTRAS = (
    "previous_code",
    "published_for_sale",
    "listed_by_owner",
    "owner_home",
    "public",
    "listed_by_special",
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-listing-redaction")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _patch_express(monkeypatch):
    monkeypatch.setattr("app.api.express.load_express_lands_cached", lambda: [dict(LAND)])
    monkeypatch.setattr("app.api.express.get_lands_file_stats", lambda: {"etag": 'W/"lands"'})


def _assert_no_private(payload):
    text = json.dumps(payload, ensure_ascii=False)
    assert OWNER not in text
    assert CONTACT not in text
    assert NATIONAL_ID not in text
    assert "مالک خصوصی" not in text
    assert "یادداشت خصوصی" not in text
    assert "owner_phone" not in text
    assert "vinor_contact" not in text
    assert "owner_name" not in text
    assert "national_id" not in text
    assert "notes" not in text
    assert "_share_token" not in text
    assert "_repost_by_name" not in text


def _assert_app_fields(land):
    for key in APP_FIELDS:
        assert land[key] == LAND[key], key
    extras = land["extras"]
    assert set(extras) == set(SAFE_EXTRAS)
    for key in SAFE_EXTRAS:
        assert extras[key] == LAND["extras"][key], key


def test_express_detail_and_list_hide_owner_contact(client, monkeypatch):
    _patch_express(monkeypatch)
    detail = client.get("/api/express/L9")
    assert detail.status_code == 200
    land = detail.get_json()["land"]
    assert land["code"] == "L9"
    assert land["title"] == "خانه تست"
    assert land["price_total"] == 2500000000
    assert land["city"] == "گرمابسرد"
    assert land["image_thumb"]
    assert land["image_full"]
    _assert_app_fields(land)
    _assert_no_private(detail.get_json())

    listing = client.get("/api/express-listings")
    assert listing.status_code == 200
    rows = listing.get_json()["lands"]
    assert rows[0]["code"] == "L9"
    assert rows[0]["image_thumb"]
    _assert_app_fields(rows[0])
    _assert_no_private(listing.get_json())


def test_home_carousel_drops_owner_contact(monkeypatch):
    monkeypatch.setattr(
        "app.express_partner.routes.load_express_lands_cached",
        lambda: [dict(LAND)],
    )
    monkeypatch.setattr(
        "app.express_partner.special_listings.ensure_unique_land_codes",
        lambda: None,
    )
    from flask import Flask

    from app.express_partner.routes import _home_public_carousel_lands

    app = Flask(__name__)
    with app.app_context():
        rows = _home_public_carousel_lands(limit=5)
    assert [row["code"] for row in rows] == ["L9"]
    assert rows[0]["title"] == "خانه تست"
    assert rows[0]["_detail_url"].endswith("/L9") or "L9" in rows[0]["_detail_url"]
    assert rows[0]["_is_public"] is True
    assert "_commission_amount" in rows[0]
    assert "_commission_pct" in rows[0]
    _assert_app_fields(rows[0])
    _assert_no_private(rows)
