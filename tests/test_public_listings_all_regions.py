# -*- coding: utf-8 -*-
"""Published listings outside گرمابسرد stay on the home feed, search, and chat."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_LANDS = [
    {
        "code": "1",
        "title": "زمین گرمابسرد",
        "city": "گرمابسرد",
        "location": "دشت اول",
        "is_express": True,
        "public": True,
        "created_at": "2026-01-03",
    },
    {
        "code": "3",
        "title": "زمین کرج",
        "city": "کرج",
        "location": "گوهردشت",
        "is_express": True,
        "public": True,
        "created_at": "2026-01-02",
    },
    {
        "code": "4",
        "title": "زمین تهران",
        "city": "تهران",
        "location": "پونک",
        "is_express": True,
        "public": True,
        "created_at": "2026-01-01",
    },
    {
        "code": "9",
        "title": "زمین فروخته‌شده",
        "city": "کرج",
        "location": "عظیمیه",
        "is_express": True,
        "public": True,
        "express_status": "sold",
        "created_at": "2026-01-04",
    },
    {
        "code": "8",
        "title": "زمین خصوصی",
        "city": "رشت",
        "location": "گلسار",
        "is_express": True,
        "public": False,
        "created_at": "2026-01-05",
    },
]


def _patch_catalog(monkeypatch):
    monkeypatch.setattr(
        "app.express_partner.routes.load_express_lands_cached",
        lambda: list(_LANDS),
    )
    monkeypatch.setattr(
        "app.express_partner.special_listings.ensure_unique_land_codes",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.express_partner.divar_pro_ads.home_divar_ads_context",
        lambda: {
            "divar_pro_ads_enabled": False,
            "divar_pro_ads": [],
            "divar_pro_ads_title": "آگهی‌ها",
        },
    )
    monkeypatch.setattr(
        "app.ai.context.load_express_lands_cached",
        lambda: list(_LANDS),
    )
    monkeypatch.setattr("app.ai.context._select_lands_by_rag", lambda *args, **kwargs: [])


def test_helper_still_recognizes_only_the_old_service_area():
    from app.utils.iran_cities import land_in_service_focus

    assert land_in_service_focus(_LANDS[0]) is True
    assert land_in_service_focus(_LANDS[1]) is False
    assert land_in_service_focus(_LANDS[2]) is False


def test_carousel_keeps_published_listings_from_other_cities(monkeypatch):
    _patch_catalog(monkeypatch)
    from flask import Flask

    from app.express_partner.routes import _home_public_carousel_lands

    app = Flask(__name__)
    with app.app_context():
        out = _home_public_carousel_lands(limit=40)
    assert [row["code"] for row in out] == ["1", "3", "4"]


def test_chat_sample_and_search_include_other_cities(monkeypatch):
    _patch_catalog(monkeypatch)
    from app.ai.agent_tools import _tool_search_lands
    from app.ai.context import _public_lands_sample, _select_lands_for_query

    sample = _public_lands_sample(10)
    assert [row["code"] for row in sample] == ["1", "3", "4"]

    picked = _select_lands_for_query(
        list(_LANDS),
        "گوهردشت",
        default_limit=5,
        match_limit=5,
    )
    assert [row["code"] for row in picked] == ["3"]

    found = _tool_search_lands(
        {"query": "کرج", "limit": 2},
        phone="09120000000",
        audience="public",
    )
    assert found["land_codes"] == ["3"]
    instruction = found["model_result"]["instruction"]
    assert "پیشنهاد نده" not in instruction
    assert found["model_result"]["lands"][0]["city"] == "کرج"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-all-regions")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    _patch_catalog(monkeypatch)

    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_home_data_and_search_return_listings_1_3_and_4(client):
    home = client.get("/express/partner/home/data", follow_redirects=False)
    assert home.status_code == 200
    assert home.is_json
    ads = home.get_json()["divar_pro_ads"]
    vinor = [ad for ad in ads if ad.get("source") == "vinor"]
    assert [ad["token"] for ad in vinor] == ["1", "3", "4"]
    assert all(ad["city"] for ad in vinor)

    search = client.get("/express/partner/search", follow_redirects=False)
    assert search.status_code == 200
    html = search.get_data(as_text=True)
    for code in ("1", "3", "4"):
        assert f'data-land-code="{code}"' in html
    assert 'data-land-code="9"' not in html
    assert 'data-land-code="8"' not in html
    assert "زمین فروخته‌شده" not in html
    assert "زمین خصوصی" not in html


def test_public_api_home_feed_filters_private_sold_and_works_without_ad_carousel(client):
    resp = client.get("/express/partner/api/public-lands", follow_redirects=False)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    ads = payload["public_lands"]
    assert [item["code"] for item in ads] == ["1", "3", "4"]
    assert all(item["published_for_sale"] is True for item in ads)
    assert all(item["source"] == "vinor" and item["url"] for item in ads)
    assert all("زمین خصوصی" != item["title"] for item in ads)


def test_public_api_limit_is_applied_after_visibility_filter(app):
    from app.express_partner.routes import _public_lands_payload

    with app.test_request_context("/express/partner/api/public-lands"):
        assert [row["code"] for row in _public_lands_payload(limit=1)] == ["1"]


def test_public_feed_accepts_numeric_size_and_unformatted_price(client, monkeypatch):
    monkeypatch.setattr(
        "app.express_partner.routes.load_express_lands_cached",
        lambda: [
            {
                "code": "41",
                "title": "ملک تست",
                "city": "تهران",
                "is_express": True,
                "public": True,
                "size": 250,
                "price": "توافقی",
                "images": ["/uploads/a.jpg"],
            }
        ],
    )
    response = client.get("/express/partner/api/public-lands")
    assert response.status_code == 200
    rows = response.get_json()["public_lands"]
    assert len(rows) == 1
    assert rows[0]["code"] == "41"
    assert rows[0]["size"] == "250"
    assert rows[0]["price_total"] == 0
    assert rows[0]["image_count"] == 1


def test_home_shows_published_cards_when_promotion_system_is_off(client, monkeypatch):
    monkeypatch.setattr(
        "app.express_partner.home_ads_config.home_ads_system_enabled",
        lambda: False,
    )
    data = client.get("/express/partner/home/data")
    assert data.status_code == 200
    home_data = data.get_json()
    ads = home_data["divar_pro_ads"]
    assert [ad["token"] for ad in ads if ad.get("source") == "vinor"] == ["1", "3", "4"]
    assert [ad["code"] for ad in home_data["public_lands"]] == ["1", "3", "4"]

    search = client.get("/express/partner/search")
    assert search.status_code == 200
    for code in ("1", "3", "4"):
        assert f'data-land-code="{code}"' in search.get_data(as_text=True)

    home = client.get("/express/partner/home")
    assert home.status_code == 200
    html = home.get_data(as_text=True)
    # Swipe gesture handles refresh; do not restore a redundant toolbar button.
    assert 'data-vn-home-refresh' not in html
    assert 'vn-home-divar__card' in html
