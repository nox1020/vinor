# -*- coding: utf-8 -*-
"""صندوق پیگیری پلاس: can_remove و فرم‌های /inbox-visits."""
from __future__ import annotations

import pytest

OWNER = "09121111000"
REQUESTER = "09123333000"
LAND = "42"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-inbox-visits")
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
    monkeypatch.setattr(
        "app.express_partner.visit_sms.notify_partner_land_tx_sms",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.express_partner.admin_action_sms.notify_admin_pending_action",
        lambda *_a, **_k: {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(
        "app.express_partner.commission_sms.notify_partner_commission_txn",
        lambda *_a, **_k: {"ok": True, "skipped": True},
    )

    class _SilentSms:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def json(self):
            return {"status": 1}

    class _SilentSmsSession:
        def post(self, *_a, **_k):
            return _SilentSms()

    monkeypatch.setattr(
        "app.services.sms._sms_http_session",
        lambda: _SilentSmsSession(),
    )
    # تست CRM تابع load را با MagicMock عوض می‌کند و import دیرهنگام همان mock را نگه می‌دارد.
    import app.express_partner.special_visit_inbox as inbox
    import app.utils.storage as storage

    monkeypatch.setattr(inbox, "load_express_partners", storage.load_express_partners)
    monkeypatch.setattr(inbox, "save_express_partners", storage.save_express_partners)
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _row(vid, *, phone, status, outcome="", customer="09120000099"):
    row = {
        "id": vid,
        "partner_phone": phone,
        "partner_name": "مشاور",
        "land_code": LAND,
        "land_title": "فایل پلاس",
        "status": status,
        "owner_phone": OWNER,
        "plus_user_phone": OWNER,
        "visit_date": "2026-11-02",
        "customer_name": "علی رضایی",
        "customer_phone": customer,
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
    }
    if outcome:
        row["visit_outcome"] = outcome
    return row


def _seed(app, visits):
    from app.utils.storage import (
        save_ads,
        save_express_assignments,
        save_express_partners,
        save_express_visit_requests,
    )

    with app.app_context():
        save_express_partners([{
            "phone": OWNER,
            "name": "پلاس",
            "status": "approved",
            "partner_tier": "special",
            "plus_expires_at": "2099-01-01T00:00:00Z",
        }])
        save_ads([{
            "code": LAND,
            "title": "فایل پلاس",
            "owner": OWNER,
            "is_express": True,
            "public": True,
            "source": "express",
            "price_total": 1_000_000,
        }])
        save_express_assignments([{
            "land_code": LAND,
            "partner_phone": REQUESTER,
            "status": "active",
        }])
        save_express_visit_requests(visits)


def _login(client):
    with client.session_transaction() as sess:
        sess["user_phone"] = OWNER


def _csrf(client) -> str:
    """توکن از خود صفحهٔ پیگیری؛ فرم کارت یا data-csrf هر کدام باشد کافی است."""
    page = client.get("/express/partner/requests")
    text = page.get_data(as_text=True)
    assert page.status_code == 200, (page.status_code, text[:240])
    assert 'id="partnerRequestsPage"' in text, text[:240]
    for marker in (
        'name="csrf_token" value="',
        'data-csrf="',
        'csrfToken: "',
    ):
        start = text.find(marker)
        if start < 0:
            continue
        start += len(marker)
        end = text.find('"', start)
        token = text[start:end].strip()
        if token:
            return token
    raise AssertionError("csrf token missing: " + text[:240])


def _post_form(client, vid, action, token):
    return client.post(
        f"/express/partner/inbox-visits/{vid}/{action}",
        data={"csrf_token": token},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": token,
        },
    )


def _follow(client, resp):
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "/express/partner/requests" in location
    assert "/login" not in location
    page = client.get(location)
    assert page.status_code == 200
    return page.get_data(as_text=True)


def test_requests_archive_filter_omits_active_chip(app, client):
    open_row = _row("open1", phone=REQUESTER, status="pending", customer="09120000081")
    archived = _row("arch1", phone=REQUESTER, status="completed", outcome="interested", customer="09120000082")
    archived["archived"] = True
    _seed(app, [open_row, archived])
    _login(client)

    page = client.get("/express/partner/requests").get_data(as_text=True)
    assert "status=active" not in page
    assert "status=archived" in page
    assert ">بایگانی " in page
    assert 'data-request-id="open1"' in page
    assert 'data-request-id="arch1"' not in page
    assert "منتظر تأیید (قدیمی)" in page

    archived_page = client.get("/express/partner/requests?status=archived").get_data(as_text=True)
    assert "status=active" not in archived_page
    assert 'data-request-id="arch1"' in archived_page
    assert 'data-request-id="open1"' not in archived_page


def test_can_remove_follows_cancel_or_delete(app, monkeypatch):
    from app.express_partner.special_visit_inbox import visits_for_special_owner

    monkeypatch.setattr(
        "app.express_partner.special_visit_inbox._visit_row_for_plus_owner",
        lambda *_a, **_k: True,
    )
    rows = [
        _row("own-open", phone=OWNER, status="pending"),
        _row("own-done", phone=OWNER, status="completed", outcome="interested"),
        _row("other-open", phone=REQUESTER, status="pending"),
    ]
    with app.app_context():
        items = visits_for_special_owner(OWNER, rows)
    by_id = {item["id"]: item for item in items}
    assert by_id["own-open"]["can_cancel"] is True
    assert by_id["own-open"]["can_remove"] is True
    assert by_id["own-done"]["can_delete"] is True
    assert by_id["own-done"]["can_remove"] is True
    assert by_id["other-open"]["can_cancel"] is False
    assert by_id["other-open"]["can_delete"] is False
    assert by_id["other-open"]["can_remove"] is False
    for item in items:
        assert item["can_remove"] is (item["can_cancel"] or item["can_delete"])


def test_plus_inbox_forms_redirect_with_flash(app, client):
    from app.utils.storage import load_express_visit_requests

    pending = _row("pend", phone=REQUESTER, status="pending", customer="09120000091")
    deal = _row(
        "dealv",
        phone=REQUESTER,
        status="completed",
        outcome="interested",
        customer="09120000092",
    )
    _seed(app, [pending, deal])
    _login(client)

    html = client.get("/express/partner/requests").get_data(as_text=True)
    assert 'action="/express/partner/inbox-visits/pend/approve"' in html
    assert 'action="/express/partner/inbox-visits/pend/reject"' in html
    assert 'action="/express/partner/inbox-visits/dealv/start_deal"' in html
    assert ">تأیید بازدید<" in html
    assert ">رد بازدید<" in html
    assert ">ثبت معامله<" in html

    token = _csrf(client)
    approved = _post_form(client, "pend", "approve", token)
    body = _follow(client, approved)
    assert "border-emerald" in body
    assert "بازدید تأیید شد" in body
    with app.app_context():
        stored = {row["id"]: row for row in load_express_visit_requests()}
    assert stored["pend"]["status"] == "approved"

    fresh = _row("rej", phone=REQUESTER, status="pending", customer="09120000093")
    with app.app_context():
        rows = list(load_express_visit_requests() or [])
        rows.append(fresh)
        from app.utils.storage import save_express_visit_requests
        save_express_visit_requests(rows)
    token = _csrf(client)
    rejected = _post_form(client, "rej", "reject", token)
    body = _follow(client, rejected)
    assert "border-emerald" in body
    assert "بازدید رد شد" in body
    with app.app_context():
        stored = {row["id"]: row for row in load_express_visit_requests()}
    assert stored["rej"]["status"] == "cancelled"

    token = _csrf(client)
    started = _post_form(client, "dealv", "start_deal", token)
    assert "/tab=deals" in started.headers["Location"] or "tab=deals" in started.headers["Location"]
    body = _follow(client, started)
    assert "border-emerald" in body
    assert "فروش نهایی ثبت شد" in body

    html = client.get("/express/partner/requests?tab=deals").get_data(as_text=True)
    assert (
        'action="/express/partner/inbox-visits/dealv/approve_deal"' in html
        or 'action="/express/partner/inbox-visits/dealv/close_deal"' in html
    )
    token = _csrf(client)
    closed = _post_form(client, "dealv", "approve_deal", token)
    body = _follow(client, closed)
    assert "border-emerald" in body
    assert "فروش نهایی تأیید شد" in body

    missing = _post_form(client, "missing", "approve", _csrf(client))
    body = _follow(client, missing)
    assert "border-amber" in body
    assert "درخواست پیدا نشد" in body
