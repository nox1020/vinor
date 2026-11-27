# -*- coding: utf-8 -*-
"""نوار خلاصهٔ «پیگیری»: سه عدد سابق «وینور من» با همان منبع داده و فیلتر قابل لمس."""
from __future__ import annotations

import re

import pytest

PARTNER = "09121234567"
PENDING_PARTNER = "09127770000"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-tracking-stats")
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
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with application.app_context():
        from app.utils import storage as S

        S.save_express_partners([
            {"phone": PARTNER, "name": "همکار", "status": "approved", "city": "تهران"},
        ])
        S.save_express_partner_apps([
            {"id": 1, "phone": PENDING_PARTNER, "name": "متقاضی", "status": "pending"},
        ])
        S.save_express_visit_requests([
            # دو ردیف باز برای یک مشتری = یک «مشتری فعال»
            {"id": "a1", "partner_phone": PARTNER, "land_code": "1", "customer_phone": "09110000001", "status": "pending"},
            {"id": "a2", "partner_phone": PARTNER, "land_code": "2", "customer_phone": "09110000001", "status": "approved"},
            {"id": "a3", "partner_phone": PARTNER, "land_code": "3", "customer_phone": "09110000002", "status": "done_pending"},
            {"id": "c1", "partner_phone": PARTNER, "land_code": "4", "customer_phone": "09110000003", "status": "completed"},
            {"id": "c2", "partner_phone": PARTNER, "land_code": "5", "customer_phone": "09110000004", "status": "completed"},
            {"id": "c3", "partner_phone": PARTNER, "land_code": "6", "customer_phone": "09110000005", "status": "completed"},
            {"id": "x1", "partner_phone": PARTNER, "land_code": "7", "customer_phone": "09110000006", "status": "cancelled"},
            {"id": "o1", "partner_phone": "09129999999", "land_code": "8", "customer_phone": "09110000007", "status": "pending"},
        ])
        S.save_express_commissions([
            {"id": 1, "commission_type": "deal", "partner_phone": PARTNER, "land_code": "4", "commission_amount": 1, "status": "approved"},
            {"id": 2, "commission_type": "deal", "partner_phone": PARTNER, "land_code": "5", "commission_amount": 1, "status": "paid"},
            {"id": 3, "commission_type": "deal", "partner_phone": PARTNER, "land_code": "6", "commission_amount": 1, "status": "pending"},
            {"id": 4, "commission_type": "manual_adjustment", "partner_phone": PARTNER, "land_code": "wallet", "commission_amount": 9, "status": "approved"},
        ])
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, phone=PARTNER):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


EXPECTED = {"active_customers": 2, "visits_done": 3, "deals_done": 2}


def test_api_exposes_same_numbers_as_former_profile_source(client):
    _login(client)
    home = client.get("/express/partner/home/data").get_json()
    data = client.get("/express/partner/api/requests/data").get_json()
    stats = data["summary_stats"]
    assert stats["visible"] is True
    assert {k: stats[k] for k in EXPECTED} == EXPECTED
    # همان منبعی که «وینور من» در APK از آن می‌خواند.
    assert stats["active_customers"] == home["home_active_customers"]
    assert stats["visits_done"] == home["home_visits_done"]
    assert stats["deals_done"] == home["home_deals_done"]
    assert data["summary_tabs"] == {
        "active_customers": "requests", "visits_done": "visits", "deals_done": "deals",
    }


def test_api_stats_ignore_tab_and_archive_view(client):
    _login(client)
    for qs in ("?tab=deals", "?status=archived", "?offers_in_cards=1"):
        stats = client.get("/express/partner/api/requests/data" + qs).get_json()["summary_stats"]
        assert {k: stats[k] for k in EXPECTED} == EXPECTED, qs


def test_tracking_page_renders_slim_strip_with_persian_digits(client):
    _login(client)
    body = client.get("/express/partner/requests").get_data(as_text=True)
    assert body.count('data-rq-stat="') == 3
    strip = body[body.index("data-rq-stats"): body.index("</nav>", body.index("data-rq-stats"))]
    assert "مشتری فعال" in strip and "بازدید" in strip and "معامله" in strip
    assert "<b>۲</b><span>مشتری فعال</span>" in strip
    assert "<b>۳</b><span>بازدید</span>" in strip
    assert "<b>۲</b><span>معامله</span>" in strip
    assert "\u0628\u0627\u0632\u0646\u0634\u0631" not in body  # retired repost label
    # pull-to-refresh و اسکرول‌بار مخفی دست نخورده‌اند.
    assert "scrollbar-width: none" in body


def test_strip_taps_switch_filter_and_toggle_back(client):
    _login(client)
    body = client.get("/express/partner/requests").get_data(as_text=True)
    links = {key: href for href, key in re.findall(r'href="([^"]+)"\s+data-vinor-express-nav\s+data-rq-stat="(\w+)"', body)}
    assert len(links) == 3
    assert links["active_customers"].endswith("/express/partner/requests?tab=requests")
    assert links["visits_done"].endswith("/express/partner/requests?tab=visits")
    assert links["deals_done"].endswith("/express/partner/requests?tab=deals")
    assert "is-active" not in body[body.index("data-rq-stats"): body.index("</nav>", body.index("data-rq-stats"))]

    active = client.get("/express/partner/requests?tab=visits").get_data(as_text=True)
    strip = active[active.index("data-rq-stats"): active.index("</nav>", active.index("data-rq-stats"))]
    assert strip.count("is-active") == 1
    m = re.search(r'href="([^"]+)"\s+data-vinor-express-nav\s+data-rq-stat="visits_done"', strip)
    assert m and m.group(1).endswith("/express/partner/requests")  # دوباره زدن = همه
    assert 'data-rq-stat-tab="visits"\n         class="rq-stat is-active"' in strip


def test_strip_hidden_in_archive_and_for_unapproved(client):
    _login(client)
    archived = client.get("/express/partner/requests?status=archived").get_data(as_text=True)
    assert "data-rq-stats" not in archived
    _login(client, PENDING_PARTNER)
    resp = client.get("/express/partner/requests")
    if resp.status_code == 200:
        assert "data-rq-stats" not in resp.get_data(as_text=True)
    data = client.get("/express/partner/api/requests/data").get_json() or {}
    if data.get("summary_stats") is not None:
        assert data["summary_stats"]["visible"] is False
