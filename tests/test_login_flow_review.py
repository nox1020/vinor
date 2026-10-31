# -*- coding: utf-8 -*-
"""Login / OTP review locks. SMS dispatch is mocked; nothing is sent."""
from __future__ import annotations

import time
from pathlib import Path
from unittest import mock

import pytest

from app.auth.otp.providers.base import KIND_SUCCESS, OTPDeliveryResult

SMS_OK = OTPDeliveryResult(success=True, provider="sms", failure_kind=KIND_SUCCESS)
PHONE = "09124000099"
TPL = Path("app/express_partner/templates/express_partner/auth")


@pytest.fixture
def app(tmp_path, monkeypatch):
    for k, v in {
        "INSTANCE_PATH": str(tmp_path), "SECRET_KEY": "unit-login-review", "SESSION_COOKIE_SECURE": "0",
        "VINOR_DISABLE_SALES_COACH_NUDGE": "1", "VINOR_DISABLE_REACH": "1", "VINOR_DISABLE_CELEBRATION_SMS": "1",
        "VINOR_DISABLE_SMS_SCHEDULER": "1", "VINOR_OPTIMIZATION_ENABLED": "0", "VINOR_OPTIMIZATION_SCHEDULER": "0",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'vinor.db'}", "VINOR_OTP_HMAC_SECRET": "unit-otp",
        "VINOR_OTP_SMS_ENABLED": "1", "VINOR_OTP_EXPOSE_IN_DEV": "0", "VINOR_OTP_TTL_SECONDS": "120",
        "VINOR_OTP_RESEND_COOLDOWN_SECONDS": "60", "VINOR_OTP_MAX_ATTEMPTS": "5", "VINOR_OTP_DIGITS": "5",
    }.items():
        monkeypatch.setenv(k, v)
    from app import create_app

    a = create_app()
    a.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _request(client, code="12345"):
    with mock.patch("app.auth.otp.service.generate_otp", return_value=code), \
         mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
        r = client.post("/express/partner/api/login-request", json={"phone": "+98 912 400 0099", "accept_legal": True})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_login_request_reports_resend_wait(client):
    body = _request(client)
    assert body["success"] and 55 <= body["retry_after"] <= 60


def test_otp_page_timer_follows_server_cooldown(client):
    _request(client)
    with client.session_transaction() as s:
        s["otp_created_at"] = time.time() - 45
    html = client.get("/express/partner/login/otp").get_data(as_text=True)
    assert "startResendCooldown(15)" in html or "startResendCooldown(16)" in html


def test_expired_otp_page_stays_and_allows_resend(client):
    _request(client)
    with client.session_transaction() as s:
        s["otp_created_at"] = time.time() - 600
    r = client.get("/express/partner/login/otp")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "startResendCooldown(0)" in html and "منقضی" in html
    with mock.patch("app.auth.otp.service.generate_otp", return_value="54321"), \
         mock.patch("app.auth.otp.service.otp_resend_cooldown_seconds", return_value=0), \
         mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
        r = client.post("/express/partner/otp/resend", json={})
    assert r.status_code == 200 and r.get_json()["ok"]


def test_too_many_attempts_says_so(client):
    _request(client, "12345")
    last = None
    for _ in range(7):
        last = client.post("/express/partner/api/verify", json={"phone": PHONE, "code": "99999"}).get_json()
    assert "تلاش" in last["error"]


def test_verify_success_sets_session_and_safe_next(client):
    _request(client, "24680")
    r = client.post(
        "/express/partner/verify",
        data={"phone": PHONE, "otp_code": "۲۴۶۸۰", "next": "//evil.example/x"},
    )
    assert r.status_code in (302, 303)
    assert "evil.example" not in r.headers["Location"]
    with client.session_transaction() as s:
        assert s.get("user_phone")


def test_web_phone_input_accepts_country_code_autofill():
    html = (TPL / "login_step1.html").read_text(encoding="utf-8")
    assert 'maxlength="11"' not in html
    assert "indexOf('98') === 0" in html and "'0098'" in html


def test_web_otp_input_autofill_attrs():
    html = (TPL / "login_step2.html").read_text(encoding="utf-8")
    assert 'autocomplete="one-time-code"' in html and 'inputmode="numeric"' in html
    assert "لطفاً برای دریافت کد کمی صبر کنید" not in html
