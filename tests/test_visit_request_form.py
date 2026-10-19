# -*- coding: utf-8 -*-
"""فرم بازدید جزئیات آگهی: نام از پروفایل و نرمال‌سازی موبایل."""
from __future__ import annotations

import pytest

from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

BUYER = "09120001111"
ADVISOR = "09120002222"
OWNER = "09120003333"
LAND = "V-19"
CANON = "09123456789"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-visit-form")
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

    class _SilentSms:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def json(self):
            return {"status": 1}

    class _SilentSmsSession:
        def post(self, *_a, **_k):
            return _SilentSms()

    monkeypatch.setattr("app.services.sms._sms_http_session", lambda: _SilentSmsSession())
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


def _seed(app):
    from app.utils.storage import save_ads, save_express_partners

    with app.app_context():
        save_express_partners([
            {"phone": BUYER, "name": "علی رضایی", "status": "pending"},
            {"phone": ADVISOR, "name": "سارا کریمی", "status": "approved"},
            {
                "phone": OWNER,
                "name": "پلاس",
                "status": "approved",
                "partner_tier": "special",
                "plus_expires_at": "2099-01-01T00:00:00Z",
            },
        ])
        save_ads([{
            "code": LAND,
            "title": "ملک بازدید",
            "is_express": True,
            "public": True,
            "price_total": 5_000_000,
            "owner": OWNER,
            "city": "تهران",
        }])


def _login(client, phone):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


def _day(app):
    with app.app_context():
        from app.express_partner.visit_requests import visit_date_min_iso

        return visit_date_min_iso()


def _post(client, phone, **fields):
    _login(client, phone)
    return client.post(
        f"/express/partner/visit-requests/{LAND}",
        data=fields,
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )


def _stored(app, phone):
    from app.utils.storage import load_express_visit_requests

    with app.app_context():
        rows = load_express_visit_requests() or []
    return next(row for row in rows if str(row.get("partner_phone") or "") == phone)


@pytest.mark.parametrize(
    "raw",
    [
        "0912 345 6789",
        "۰۹۱۲۳۴۵۶۷۸۹",
        "٠٩١٢٣٤٥٦٧٨٩",
        "+98 912 345 6789",
        "+98 0912 345 6789",
        "0098 912 345 6789",
        "98 912 345 6789",
        "0912-345-6789",
        "0912–345–6789",
    ],
)
def test_phone_formats_canonicalize(raw):
    assert normalize_iran_mobile(raw) == CANON
    assert is_valid_iran_mobile(normalize_iran_mobile(raw))


@pytest.mark.parametrize("raw", ["12345", "0912", "02112345678", "091234567890"])
def test_phone_formats_reject_invalid(raw):
    assert not is_valid_iran_mobile(normalize_iran_mobile(raw))


def test_buyer_page_hides_customer_fields_and_api_prefills(app, client):
    _seed(app)
    _login(client, BUYER)
    page = client.get(f"/express/partner/lands/{LAND}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert ">بازدید<" in html
    assert 'name="customer_first_name"' not in html
    assert "نام مشتری" not in html
    assert "علی رضایی" in html
    assert BUYER in html or "09120001111" in html
    assert 'data-is-advisor="0"' in html

    status = client.get(
        f"/express/partner/lands/{LAND}/tx-status",
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    body = status.get_json()
    assert status.status_code == 200
    assert body["success"] is True
    assert body["is_advisor"] is False
    assert body["show_customer_fields"] is False
    assert body["customer_name_optional"] is True
    assert body["customer_phone_optional"] is True
    assert body["prefilled_name"] == "علی رضایی"
    assert body["prefilled_phone"] == BUYER
    assert body["tx_mode"] == "visit"
    assert body["visit_date_min"]
    assert body["visit_allowed_hours"]

    data = client.get(f"/express/partner/api/lands/{LAND}/data")
    payload = data.get_json()
    assert payload["is_advisor"] is False
    assert payload["prefilled_name"] == "علی رضایی"
    assert payload["prefilled_phone"] == BUYER
    assert payload["can_request_visit"] is True


def test_advisor_page_shows_optional_customer_fields(app, client):
    _seed(app)
    _login(client, ADVISOR)
    html = client.get(f"/express/partner/lands/{LAND}").get_data(as_text=True)
    assert "نام مشتری" in html
    assert "نام خانوادگی" in html
    assert "موبایل" in html
    assert "اختیاری" in html
    assert 'name="customer_first_name"' in html
    assert 'name="customer_last_name"' in html
    assert 'name="customer_phone"' in html
    assert 'data-is-advisor="1"' in html
    assert 'name="customer_phone" required' not in html
    assert 'name="customer_first_name" required' not in html


def test_buyer_stores_profile_name_and_phone_ignoring_typed_fields(app, client):
    _seed(app)
    response = _post(
        client,
        BUYER,
        visit_date=_day(app),
        visit_time="10:00",
        customer_first_name="نباید",
        customer_last_name="ذخیره شود",
        customer_phone="12345",
    )
    body = response.get_json()
    assert response.status_code == 200, body
    assert body["success"] is True
    row = _stored(app, BUYER)
    assert row["customer_name"] == "علی رضایی"
    assert row["customer_first_name"] == "علی"
    assert row["customer_last_name"] == "رضایی"
    assert row["customer_phone"] == BUYER
    assert row["partner_name"] == "علی رضایی"


def test_advisor_empty_customer_name_uses_advisor_name(app, client):
    _seed(app)
    response = _post(client, ADVISOR, visit_date=_day(app), visit_time="11:00")
    body = response.get_json()
    assert response.status_code == 200, body
    row = _stored(app, ADVISOR)
    assert row["customer_name"] == "سارا کریمی"
    assert row["customer_phone"] == ""
    assert row["partner_name"] == "سارا کریمی"


def test_advisor_customer_name_and_phone_formats(app, client):
    _seed(app)
    day = _day(app)
    for raw in (
        "0912 345 6789",
        "۰۹۱۲۳۴۵۶۷۸۹",
        "٠٩١٢٣٤٥٦٧٨٩",
        "+98 912 345 6789",
        "0098-912-345-6789",
        "98 912 345 6789",
        "0912–345–6789",
    ):
        response = _post(
            client,
            ADVISOR,
            visit_date=day,
            visit_time="12:00",
            customer_first_name="نگار",
            customer_last_name="احمدی",
            customer_phone=raw,
        )
        body = response.get_json()
        assert response.status_code == 200, (raw, body)
        row = _stored(app, ADVISOR)
        assert row["customer_name"] == "نگار احمدی"
        assert row["customer_phone"] == CANON


def test_advisor_invalid_phone_is_rejected_in_persian(app, client):
    _seed(app)
    response = _post(
        client,
        ADVISOR,
        visit_date=_day(app),
        visit_time="13:00",
        customer_phone="12345",
    )
    body = response.get_json()
    assert response.status_code == 400
    assert body["success"] is False
    assert body["message"] == "شماره تماس مشتری معتبر نیست."
    from app.utils.storage import load_express_visit_requests

    with app.app_context():
        assert not (load_express_visit_requests() or [])
