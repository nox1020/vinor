# -*- coding: utf-8 -*-
"""جستجوی فاز A — فیلتر قیمت سمت سرور و حالت خالی."""
from __future__ import annotations

import pytest

_ADS = [
    {
        "token": "one",
        "title": "آگهی یک میلیاردی",
        "price": "۱ میلیارد تومان",
        "source": "divar",
        "location": "۳ ساعت پیش در ونک",
        "url": "/express/partner/divar/one",
    },
    {
        "token": "three",
        "title": "آگهی سه میلیاردی",
        "price": "۳٬۰۰۰٬۰۰۰٬۰۰۰ تومان",
        "price_total": 3_000_000_000,
        "source": "vinor",
        "size": 120,
        "location": "تهران، جردن",
        "url": "/express/partner/lands/three",
    },
    {
        "token": "deal",
        "title": "آگهی توافقی",
        "price": "توافقی",
        "source": "divar",
        "location": "در الهیه",
        "url": "/express/partner/divar/deal",
    },
]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-search-page")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")

    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def search_ads(monkeypatch):
    monkeypatch.setattr(
        "app.express_partner.routes._home_ads_for_api",
        lambda: (list(_ADS), len(_ADS)),
    )


def test_price_range_keeps_only_matching_ad(client, search_ads):
    resp = client.get(
        "/express/partner/search"
        "?price_min=2000000000&price_max=5000000000&sort=price_asc"
    )
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200, html[:500]
    assert "۲\u2013۵ میلیارد" in html
    assert 'aria-pressed="true"' in html
    assert 'value="price_asc" checked' in html
    assert "ارزان‌ترین" in html
    assert "آگهی سه میلیاردی" in html
    assert "آگهی یک میلیاردی" not in html
    assert "آگهی توافقی" not in html

    empty = client.get("/express/partner/search?price_min=99000000000")
    empty_html = empty.get_data(as_text=True)
    assert empty.status_code == 200, empty_html[:500]
    assert "آگهی‌ای با این فیلترها پیدا نشد" in empty_html
    assert "حذف فیلترها" in empty_html
    assert "آگهی سه میلیاردی" not in empty_html


def test_invalid_query_is_ignored(client, search_ads):
    resp = client.get(
        "/express/partner/search?sort=nope&price_min=abc&area_min=-5&rooms=2"
    )
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200, html[:500]
    assert "آگهی یک میلیاردی" in html
    assert "آگهی سه میلیاردی" in html
    assert "آگهی توافقی" in html
