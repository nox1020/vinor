# -*- coding: utf-8 -*-
"""Invest settings: annual_withdrawal_pct persistence."""
from __future__ import annotations

from datetime import timedelta

import pytest

OWNER = "09120000000"
OTHER = "09121111111"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-invest-pwo")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_INVEST_ENABLED", "1")
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
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, phone: str) -> None:
    with client.session_transaction() as sess:
        sess["user_phone"] = phone



S = "/invest/api/v1/settings"


def test_annual_pct_persists_and_is_scoped(client):
    _login(client, OWNER)
    r = client.put(S, json={"annual_withdrawal_pct": 25})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["settings"]["annual_withdrawal_pct"] == 25
    assert client.get(S).get_json()["settings"]["annual_withdrawal_pct"] == 25
    # other settings put without the key keeps it
    client.put(S, json={"theme": "dark"})
    assert client.get(S).get_json()["settings"]["annual_withdrawal_pct"] == 25
    _login(client, OTHER)
    assert "annual_withdrawal_pct" not in client.get(S).get_json()["settings"]


@pytest.mark.parametrize("bad", [0, 101, "abc", None, -5])
def test_annual_pct_validation(client, bad):
    _login(client, OWNER)
    client.put(S, json={"annual_withdrawal_pct": 30})
    r = client.put(S, json={"annual_withdrawal_pct": bad, "theme": "light"})
    assert r.status_code == 400
    s = client.get(S).get_json()["settings"]
    assert s["annual_withdrawal_pct"] == 30
