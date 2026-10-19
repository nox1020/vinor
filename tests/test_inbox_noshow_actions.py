# -*- coding: utf-8 -*-
"""کارت دریافتی عدم‌حضور: بایگانی مالک و نمایش ملک فقط وقتی جزئیات باز می‌شود."""
from __future__ import annotations

import pytest

OWNER = "09121111000"
REQUESTER = "09123333000"
OTHER = "09124444000"
PRIVATE = "77"
HIDDEN = "88"
STOPPED = "91"
CURRENT = "90"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-noshow-actions")
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
    import app.express_partner.special_visit_inbox as inbox
    import app.utils.storage as storage

    monkeypatch.setattr(inbox, "load_express_partners", storage.load_express_partners)
    monkeypatch.setattr(inbox, "save_express_partners", storage.save_express_partners)
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _visit(vid, code, customer):
    return {
        "id": vid,
        "partner_phone": REQUESTER,
        "partner_name": "مشاور",
        "land_code": code,
        "land_title": "فایل بازدید",
        "status": "no_show",
        "plus_user_phone": OWNER,
        "visit_date": "2026-11-02",
        "customer_name": "مشتری",
        "customer_phone": customer,
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-02T00:00:00Z",
    }


def _private(code, owner, title):
    return {
        "code": code,
        "title": title,
        "owner": owner,
        "source": "my_property",
        "is_express": False,
        "public": False,
        "owner_home": True,
        "archived": True,
        "archived_reason": "inactive",
        "price_total": 1_000_000,
        "extras": {
            "published_for_sale": False,
            "listed_by_owner": True,
            "owner_home": True,
        },
    }


def _seed(app):
    from app.utils.storage import save_ads, save_express_partners, save_express_visit_requests

    with app.app_context():
        save_express_partners([
            {
                "phone": OWNER,
                "name": "پلاس",
                "status": "approved",
                "partner_tier": "special",
                "plus_expires_at": "2099-01-01T00:00:00Z",
            },
            {"phone": REQUESTER, "name": "مشاور", "status": "approved"},
        ])
        save_ads([
            _private(PRIVATE, OWNER, "ملک متوقف مالک"),
            _private(HIDDEN, OTHER, "ملک دیگران"),
            {
                "code": STOPPED,
                "title": "آگهی متوقف اکسپرس",
                "owner": "989121111000",
                "is_express": True,
                "public": False,
                "source": "express",
                "archived": True,
                "archived_reason": "inactive",
                "price_total": 2_000_000,
            },
            {
                "code": CURRENT,
                "title": "ملک با کد قبلی",
                "owner": OWNER,
                "source": "my_property",
                "is_express": False,
                "public": False,
                "owner_home": True,
                "price_total": 3_000_000,
                "extras": {
                    "previous_code": "89",
                    "published_for_sale": False,
                    "listed_by_owner": True,
                    "owner_home": True,
                },
            },
        ])
        save_express_visit_requests([
            _visit("noshow-private", PRIVATE, "09120000081"),
            _visit("noshow-hidden", HIDDEN, "09120000082"),
            _visit("noshow-missing", "4040", "09120000083"),
            _visit("noshow-prev", "89", "09120000084"),
            _visit("noshow-stopped", STOPPED, "09120000085"),
        ])


def _login(client, phone):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


def _cards(client):
    payload = client.get("/express/partner/api/requests/data").get_json()
    return {str(card.get("id")): card for card in payload.get("cards") or []}


def test_owner_archives_incoming_noshow_under_lock(app, client, monkeypatch):
    from app.express_partner import visit_requests as visits
    from app.utils.storage import load_express_visit_requests

    _seed(app)
    entered = {"n": 0}
    real_lock = visits.visit_store_lock

    def wrapped(*args, **kwargs):
        entered["n"] += 1
        return real_lock(*args, **kwargs)

    monkeypatch.setattr(visits, "visit_store_lock", wrapped)
    _login(client, OTHER)
    denied = client.post("/express/partner/api/requests/noshow-private/archive", json={})
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "دسترسی ندارید."
    assert entered["n"] == 1

    _login(client, OWNER)
    saved = client.post("/express/partner/api/requests/noshow-private/archive", json={})
    assert saved.status_code == 200
    body = saved.get_json()
    assert body["ok"] is True
    assert body["archived"] is True
    again = client.post("/express/partner/api/requests/noshow-private/archive", json={})
    assert again.status_code == 200
    assert again.get_json()["already"] is True
    with app.app_context():
        row = next(item for item in load_express_visit_requests() if item["id"] == "noshow-private")
    assert row["archived"] is True
    assert entered["n"] >= 3

    _login(client, REQUESTER)
    own = client.post("/express/partner/api/requests/noshow-hidden/archive", json={})
    assert own.status_code == 200
    assert own.get_json()["ok"] is True


def test_card_flags_match_what_detail_would_load(app, client):
    _seed(app)
    _login(client, OWNER)
    cards = _cards(client)
    private = cards["noshow-private"]
    hidden = cards["noshow-hidden"]
    missing = cards["noshow-missing"]
    previous = cards["noshow-prev"]
    stopped = cards["noshow-stopped"]
    assert private["status"] == "no_show"
    assert private["direction"] == "incoming"
    assert private["can_archive"] is True
    assert private["land_available"] is True
    assert private["can_view_land"] is True
    assert hidden["can_archive"] is True
    assert hidden["land_available"] is False
    assert hidden["can_view_land"] is False
    assert missing["can_archive"] is True
    assert missing["land_available"] is False
    assert missing["can_view_land"] is False
    assert previous["can_view_land"] is True
    assert previous["land_available"] is True
    assert stopped["can_view_land"] is True
    assert stopped["land_available"] is True

    owned = client.get(f"/express/partner/api/lands/{PRIVATE}/data")
    assert owned.status_code == 200
    detail = owned.get_json()
    assert detail["ok"] is True
    assert detail["title"] == "ملک متوقف مالک"
    assert detail["published_for_sale"] is False
    assert detail["is_mine"] is True
    old_code = client.get("/express/partner/api/lands/89/data")
    assert old_code.status_code == 200
    assert old_code.get_json()["ok"] is True
    assert old_code.get_json()["code"] == CURRENT
    stopped_detail = client.get(f"/express/partner/api/lands/{STOPPED}/data")
    assert stopped_detail.status_code == 200
    assert stopped_detail.get_json()["ok"] is True
    assert stopped_detail.get_json()["title"] == "آگهی متوقف اکسپرس"

    _login(client, REQUESTER)
    blocked = client.get(f"/express/partner/api/lands/{PRIVATE}/data")
    assert blocked.status_code == 404
    assert blocked.get_json()["error"] == "این آگهی دیگر در دسترس نیست."
    gone = client.get("/express/partner/api/lands/4040/data")
    assert gone.status_code == 404
    assert gone.get_json()["error"] == "آگهی پیدا نشد."
    requester_cards = _cards(client)
    assert requester_cards["noshow-private"]["can_archive"] is True
    assert requester_cards["noshow-private"]["can_view_land"] is False
    assert requester_cards["noshow-stopped"]["can_view_land"] is False


def test_website_hides_archive_and_land_when_unavailable(app, client):
    _seed(app)
    _login(client, OWNER)
    page = client.get("/express/partner/requests")
    text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert text.count("بایگانی این پیگیری") == 5
    assert text.count("مشاهده فایل") == 3
    assert "عدم حضور" in text

    _login(client, REQUESTER)
    requester = client.get("/express/partner/requests").get_data(as_text=True)
    assert requester.count("بایگانی این پیگیری") == 5
    assert "مشاهده فایل" not in requester
