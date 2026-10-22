# -*- coding: utf-8 -*-
"""Invest biz: property trades + monthly table."""
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



B = "/invest/api/v1/biz"


def _seed():
    return {"trades": [
        {"buy_date": "20/01/1405", "sell_date": "21/01/1405", "buy_amount": 100, "sell_amount": 175,
         "area": 250, "title": "معامله 1"},
        {"buy_date": "10/10/1404", "sell_date": "28/01/1405", "buy_amount": 50, "sell_amount": 80,
         "area": 200, "title": "معامله 2"},
        {"buy_date": "30/07/1404", "sell_date": "29/01/1405", "buy_amount": 60, "sell_amount": 100,
         "title": "معامله 3", "extra_cost": 7},
    ], "months": [
        {"year": 1405, "month": 1, "staff": 10, "ads": 5, "income": 100},
        {"year": 1405, "month": 2, "staff": 20, "ads": 6, "income": 0},
    ]}


def test_requires_auth(client):
    assert client.get(B).status_code == 401
    assert client.post(B + "/import", json={}).status_code == 401


def test_import_matches_sheet_and_is_guarded(client):
    _login(client, OWNER)
    r = client.post(B + "/import", json=_seed())
    assert r.status_code == 200, r.get_json()
    biz = client.get(B + "?year=1405").get_json()["biz"]
    assert len(biz["trades"]) == 3
    assert biz["trades_totals"]["profit"] == 75 + 30 + 40
    assert biz["trades_totals"]["extra_cost"] == 7
    t = {x["title"]: x for x in biz["trades"]}
    assert t["معامله 2"]["days"] == 107
    assert t["معامله 3"]["days"] == 178
    assert round(t["معامله 1"]["profit_pct"]) == 43  # profit / sell
    assert t["معامله 1"]["buy_date"] == "1405/01/20"
    assert [m["net"] for m in biz["months"][:3]] == [85, -26, 0]
    assert biz["months_totals"]["income"] == 100 and biz["months_totals"]["net"] == 59
    # second import never writes
    r = client.post(B + "/import", json=_seed())
    assert r.get_json()["already_has_data"] is True
    assert len(client.get(B).get_json()["biz"]["trades"]) == 3
    _login(client, OTHER)
    assert client.get(B).get_json()["biz"]["trades"] == []


def test_pwo_column_comes_from_pwo_module(client):
    _login(client, OWNER)
    pwo = client.get("/invest/api/v1/pwo").get_json()["pwo"]
    wid = pwo["withdrawers"][0]["id"]
    client.put("/invest/api/v1/pwo/months/1405/1", json={"amounts": {str(wid): 126_700_000}})
    client.put(B + "/months/1405/1", json={"staff": 18_000_000, "ads": 69_600_000, "income": 1_109_000_000})
    m1 = client.get(B + "?year=1405").get_json()["biz"]["months"][0]
    assert m1["pwo"] == 126_700_000
    assert m1["net"] == 894_700_000  # as in the sheet


def test_trade_crud_and_validation(client):
    _login(client, OWNER)
    r = client.post(B + "/trades", json={"buy_date": "1405/02/01", "buy_amount": "۱۰۰,۰۰۰"})
    assert r.status_code == 200, r.get_json()
    tr = r.get_json()["biz"]["trades"][0]
    assert tr["profit"] is None and tr["days"] is None
    r = client.put(f"{B}/trades/{tr['id']}", json={"sell_date": "1405/02/11", "sell_amount": 150000})
    tr = r.get_json()["biz"]["trades"][0]
    assert tr["profit"] == 50000 and tr["days"] == 10
    for bad in ({"buy_date": "1405/13/01", "buy_amount": 1}, {"buy_date": "1405/02/01", "buy_amount": 0},
                {"buy_date": "1405/02/05", "buy_amount": 1, "sell_date": "1405/02/01", "sell_amount": 2},
                {"buy_date": "1405/02/05", "buy_amount": 1, "sell_amount": 2}):
        assert client.post(B + "/trades", json=bad).status_code == 400
    assert client.delete(f"{B}/trades/{tr['id']}").status_code == 200
    assert client.delete(f"{B}/trades/{tr['id']}").status_code == 404
    assert client.put(B + "/months/1405/13", json={"staff": 1}).status_code == 400
    client.put(B + "/months/1405/2", json={"income": 5})
    assert client.delete(B + "/months/1405/2").status_code == 200
