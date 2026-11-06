# -*- coding: utf-8 -*-
""" /api/sms is admin-session only. Anonymous and partner callers cannot send or read."""
from __future__ import annotations

from unittest import mock

import pytest

_ENV = {
    "SESSION_COOKIE_SECURE": "0",
    "VINOR_DISABLE_SMS_SCHEDULER": "1",
    "VINOR_DISABLE_REACH": "1",
    "VINOR_DISABLE_CELEBRATION_SMS": "1",
    "VINOR_DISABLE_SALES_COACH_NUDGE": "1",
    "VINOR_OPTIMIZATION_SCHEDULER": "0",
    "VINOR_CELEBRATION_SMS_SCHEDULER": "0",
    "VINOR_SALES_COACH_SCHEDULER": "0",
    "VINOR_REACH_SCHEDULER": "0",
    "VINOR_ADMIN_SMS_SCHEDULER": "0",
    "SMS_API_KEY": "pytest-dummy-sms-api-key",
}

PATHS = (
    ("GET", "/api/sms/status", None),
    ("GET", "/api/sms/history", None),
    ("POST", "/api/sms/send", {"mobile": "09120000000", "template_id": 1}),
    ("POST", "/api/sms/bulk-send", {"mobiles": ["09120000000"], "template_id": 1}),
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-sms-api")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sms-api.db'}")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "pytest-dummy-vapid-private")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pytest-dummy-vapid-public")
    monkeypatch.setenv("VINOR_WEBHOOK_SECRET", "pytest-dummy-webhook-secret")
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _call(client, method, path, body, headers=None):
    headers = headers or {}
    if method == "GET":
        return client.get(path, headers=headers)
    return client.post(path, json=body, headers=headers)


def _csrf_headers(client):
    client.get("/express/partner/login")
    cookie = client.get_cookie("XSRF-TOKEN")
    token = getattr(cookie, "value", cookie)
    assert token, "login page did not issue a CSRF cookie"
    return {
        "X-CSRFToken": token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _admin(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["admin_phone"] = "09120000000"
        sess["username"] = "admin"


def test_anonymous_sms_routes_are_unauthorized(client):
    with mock.patch("app.api.sms.send_sms_template") as send:
        for method, path, body in PATHS:
            resp = _call(client, method, path, body)
            assert resp.status_code == 401, (path, resp.status_code, resp.get_data(as_text=True)[:200])
            payload = resp.get_json()
            assert payload["success"] is False
            assert payload["error"] == "unauthorized"
            assert "history" not in payload
            assert "api_key_configured" not in payload
        send.assert_not_called()


def test_partner_and_half_admin_sessions_are_forbidden(client):
    with client.session_transaction() as sess:
        sess["user_phone"] = "09121111111"
    partner = client.get("/api/sms/history")
    assert partner.status_code == 403
    assert partner.get_json()["error"] == "forbidden"

    with client.session_transaction() as sess:
        sess.clear()
        sess["logged_in"] = True
    half = client.post("/api/sms/send", json={"mobile": "09120000000", "template_id": 1})
    assert half.status_code == 403
    assert half.get_json()["error"] == "forbidden"


def test_admin_can_read_status_and_history(client, app):
    from app.utils.storage import save_sms_history

    with app.app_context():
        save_sms_history([
            {
                "id": 1,
                "mobile": "09123334444",
                "success": True,
                "source": "system",
                "created_at": "2026-01-01T00:00:00",
                "message": "hello",
            }
        ])
    _admin(client)
    status = client.get("/api/sms/status")
    assert status.status_code == 200
    body = status.get_json()
    assert body["success"] is True
    assert body["api_key_configured"] is True
    assert body["stats"]["total_records"] == 1

    history = client.get("/api/sms/history")
    assert history.status_code == 200
    rows = history.get_json()["history"]
    assert rows[0]["mobile"] == "09123334444"


def test_admin_send_and_bulk_require_csrf_and_then_send(client):
    _admin(client)
    with mock.patch("app.api.sms.send_sms_template", return_value={"ok": True, "status": 200, "body": {}}) as send:
        missing = client.post(
            "/api/sms/send",
            json={"mobile": "09120000000", "template_id": 7, "parameters": {"NAME": "A"}},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        assert missing.status_code == 400
        assert missing.get_json()["error"] == "csrf_expired"
        send.assert_not_called()

        headers = _csrf_headers(client)
        one = client.post(
            "/api/sms/send",
            json={"mobile": "09120000000", "template_id": 7, "parameters": {"NAME": "A"}},
            headers=headers,
        )
        assert one.status_code == 200
        assert one.get_json()["success"] is True
        assert send.call_count == 1

        headers = _csrf_headers(client)
        bulk = client.post(
            "/api/sms/bulk-send",
            json={"mobiles": ["09120000000", "bad"], "template_id": 7},
            headers=headers,
        )
        assert bulk.status_code == 200
        payload = bulk.get_json()
        assert payload["results"]["sent"] == 1
        assert payload["results"]["failed_count"] == 1
        assert send.call_count == 2


def test_sms_routes_are_not_cross_origin(client):
    _admin(client)
    sms = client.get("/api/sms/status", headers={"Origin": "https://evil.example"})
    assert sms.status_code == 200
    assert not sms.headers.get("Access-Control-Allow-Origin")

    other = client.get("/api/menu", headers={"Origin": "https://evil.example"})
    # The rest of /api still reflects any Origin. Only /api/sms is closed.
    assert other.headers.get("Access-Control-Allow-Origin") == "https://evil.example"


def test_otp_request_stays_public(client):
    from app.auth.otp.providers.base import KIND_SUCCESS, OTPDeliveryResult

    ok = OTPDeliveryResult(success=True, provider="sms", failure_kind=KIND_SUCCESS)
    with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=ok):
        resp = client.post("/auth/request-otp", json={"phone": "09120000001"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
