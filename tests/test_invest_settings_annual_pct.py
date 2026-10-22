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


def test_client_extras_persist_and_echo(client):
    _login(client, OWNER)
    body = {
        "client_withdrawals": [{"id": 1, "amount": 5, "note": "n", "created_at": "2026-01-01", "status": "done"}],
        "price_alerts": [{"symbol": "USDT", "target": 1}],
        "profit_alerts": [],
        "year_nav_history": [{"year_key": "1404", "nav_toman": 9}],
        "notify_background": False,
        "app_lock_hash": "abc",
        "app_lock_biometric": True,
    }
    r = client.put(S, json=body)
    assert r.status_code == 200, r.get_json()
    for got in (r.get_json()["settings"], client.get(S).get_json()["settings"]):
        for k, v in body.items():
            assert got[k] == v, k
    # a later save without these keys keeps them
    client.put(S, json={"theme": "dark"})
    assert client.get(S).get_json()["settings"]["client_withdrawals"][0]["amount"] == 5
    # emptying the list is allowed (deleting the last withdrawal)
    client.put(S, json={"client_withdrawals": []})
    assert client.get(S).get_json()["settings"]["client_withdrawals"] == []
    _login(client, OTHER)
    assert "client_withdrawals" not in client.get(S).get_json()["settings"]


@pytest.mark.parametrize("bad", [
    {"client_withdrawals": "nope"}, {"price_alerts": {"a": 1}}, {"price_alerts": [1, 2]},
    {"notify_background": "maybe"}, {"app_lock_hash": 5},
])
def test_client_extras_validation_writes_nothing(client, bad):
    _login(client, OWNER)
    r = client.put(S, json={**bad, "annual_withdrawal_pct": 40, "theme": "light"})
    assert r.status_code == 400
    s = client.get(S).get_json()["settings"]
    assert "annual_withdrawal_pct" not in s and s["theme"] != "light"
