# -*- coding: utf-8 -*-
"""After OTP success the user never lands on /login again."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from app.auth.otp.providers.base import KIND_SUCCESS, OTPDeliveryResult

SMS_OK = OTPDeliveryResult(success=True, provider="sms", failure_kind=KIND_SUCCESS)
AUTH = Path("app/express_partner/templates/express_partner/auth")


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k, v in {
        "INSTANCE_PATH": str(tmp_path), "SECRET_KEY": "unit-no-loop", "SESSION_COOKIE_SECURE": "0",
        "VINOR_DISABLE_SMS_SCHEDULER": "1", "VINOR_DISABLE_REACH": "1", "VINOR_OPTIMIZATION_SCHEDULER": "0",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'v.db'}", "VINOR_OTP_HMAC_SECRET": "unit",
        "VINOR_OTP_SMS_ENABLED": "1", "VINOR_OTP_EXPOSE_IN_DEV": "0", "VINOR_OTP_DIGITS": "5",
    }.items():
        monkeypatch.setenv(k, v)
    from app import create_app

    a = create_app()
    a.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return a.test_client()


def _login(client, nxt, phone="09124000088"):
    with mock.patch("app.auth.otp.service.generate_otp", return_value="13579"), \
         mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
        client.post("/express/partner/login", data={"phone": phone, "accept_legal": "1", "next": nxt})
    return client.post(
        "/express/partner/verify",
        data={"phone": phone, "otp_code": "13579", "next": nxt},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    ).get_json()


@pytest.mark.parametrize("nxt", [
    "/express/partner/login", "/express/partner/login?next=/express/partner/requests",
    "/express/partner/login/otp", "/express/partner/verify",
])
def test_next_pointing_at_login_never_returns_to_login(client, nxt):
    body = _login(client, nxt)
    assert body["ok"]
    assert "/express/partner/login" not in body["redirect"] and "/verify" not in body["redirect"]


def test_next_to_real_page_is_kept_and_login_then_redirects_away(client):
    body = _login(client, "/express/partner/requests")
    assert body["redirect"].startswith("/express/partner/requests")
    for path in ("/express/partner/login", "/express/partner/login/otp"):
        r = client.get(path)
        assert r.status_code in (302, 303) and "/login" not in r.headers["Location"]


def test_client_replaces_history_and_sanitizes_dest():
    s2 = (AUTH / "login_step2.html").read_text(encoding="utf-8")
    assert "window.location.replace(target)" in s2 and "safeAfterLoginDest" in s2
    assert "vinorPostLoginNavigate(dest)" not in s2
    s1 = (AUTH / "login_step1.html").read_text(encoding="utf-8")
    assert "{ forward: 1, replace: true }" in s1
    sw = Path("app/static/express-partner-sw.js").read_text(encoding="utf-8")
    assert "response.redirected && isAuthPartnerPath" in sw
