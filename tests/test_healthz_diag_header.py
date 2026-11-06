# -*- coding: utf-8 -*-
"""Diag /healthz routes accept the webhook secret only in a header."""
from __future__ import annotations

from unittest import mock

import pytest

SECRET = "diag-header-only"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-healthz-header")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return app.test_client()


def test_query_token_does_not_open_healthz_otp(client):
    denied = client.get("/healthz/otp", query_string={"token": SECRET})
    assert denied.status_code == 401
    assert SECRET not in denied.get_data(as_text=True)

    with mock.patch(
        "app.auth.otp.send_log.fetch_sms_ir_account",
        return_value={"credit": {"http": 200, "body": {}}, "lines": None},
    ), mock.patch("app.auth.otp.send_log.recent_attempts", return_value=[]):
        allowed = client.get("/healthz/otp", headers={"X-Vinor-Otp-Diag": SECRET})
    assert allowed.status_code == 200
    assert allowed.get_json()["ok"] is True
    assert SECRET not in allowed.get_data(as_text=True)


def test_wrong_header_is_rejected(client):
    resp = client.get("/healthz/sale-publish-sweep", headers={"X-Vinor-Otp-Diag": "nope"})
    assert resp.status_code == 401
