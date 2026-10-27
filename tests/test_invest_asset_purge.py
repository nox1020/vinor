# -*- coding: utf-8 -*-
"""Invest: user-initiated asset purge (asset + its trades), additive endpoint."""
from __future__ import annotations

from datetime import timedelta

import pytest

OWNER = "09120000000"
OTHER = "09121111111"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-invest-checks")
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



def test_purge_removes_asset_and_all_its_trades_only(client):
    _login(client, OWNER)
    base = "/invest/api/v1"
    a = client.post(f"{base}/assets", json={"name": "طلا", "current_price": 10}).get_json()["item"]
    b = client.post(f"{base}/assets", json={"name": "دلار", "current_price": 5}).get_json()["item"]
    t1 = client.post(f"{base}/trades/buy", json={"asset_id": a["id"], "quantity": 2, "buy_price": 8}).get_json()["item"]
    client.post(f"{base}/trades/buy", json={"asset_id": a["id"], "quantity": 1, "buy_price": 9})
    client.post(f"{base}/trades/{t1['id']}/sell", json={"sell_price": 12})
    client.post(f"{base}/trades/buy", json={"asset_id": b["id"], "quantity": 3, "buy_price": 4})

    # Old route still refuses while an open lot exists (unchanged behaviour).
    assert client.delete(f"{base}/assets/{a['id']}").status_code == 400

    # Confirmation is required.
    assert client.post(f"{base}/assets/{a['id']}/purge", json={}).status_code == 400

    r = client.post(f"{base}/assets/{a['id']}/purge", json={"confirm": True})
    assert r.status_code == 200 and r.get_json()["deleted"] is True
    assets = client.get(f"{base}/assets").get_json()["items"]
    assert [x["id"] for x in assets] == [b["id"]]
    open_ = client.get(f"{base}/trades/open").get_json()["items"]
    closed = client.get(f"{base}/trades/closed").get_json()["items"]
    assert {t["asset_id"] for t in open_} == {b["id"]}
    assert closed == []

    # Idempotent retry.
    again = client.post(f"{base}/assets/{a['id']}/purge", json={"confirm": True})
    assert again.status_code == 200 and again.get_json()["deleted"] is False

    # Another account cannot touch it.
    _login(client, OTHER)
    gone = client.post(f"{base}/assets/{b['id']}/purge", json={"confirm": True}).get_json()
    assert gone["deleted"] is False
    _login(client, OWNER)
    assert len(client.get(f"{base}/assets").get_json()["items"]) == 1
