# -*- coding: utf-8 -*-
"""PWO Invest: per-account، برداشت‌کننده‌ها، ماه‌ها، هدف و مهاجرت."""
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



API = "/invest/api/v1/pwo"


def _get(client):
    r = client.get(API)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["pwo"]


def test_requires_auth(client):
    for method, path in (("get", API), ("put", API + "/target"), ("post", API + "/withdrawers"),
                         ("post", API + "/entries"), ("post", API + "/import")):
        r = getattr(client, method)(path, json={})
        assert r.status_code == 401
        assert r.get_json()["error"] == "auth_required"


def test_defaults(client):
    _login(client, OWNER)
    p = _get(client)
    assert p["target"] == 100_000_000
    assert [w["name"] for w in p["withdrawers"]] == ["M", "A", "N"]
    assert p["entries"] == []


def test_entries_totals_and_target(client):
    _login(client, OWNER)
    ws = {w["name"]: w["id"] for w in _get(client)["withdrawers"]}
    r = client.put(f"{API}/months/1405/1", json={"amounts": {str(ws["M"]): "۹۶٬۷۰۰٬۰۰۰", str(ws["A"]): 15_000_000}})
    assert r.status_code == 200
    r = client.post(API + "/entries", json={"withdrawer_id": ws["N"], "year": 1405, "month": 1, "amount": "15,000,000"})
    p = r.get_json()["pwo"]
    m = p["totals"]["months"][0]
    assert m["total"] == 126_700_000 and m["met_target"] is True
    client.put(API + "/target", json={"target": 200_000_000})
    p = _get(client)
    assert p["target"] == 200_000_000 and p["totals"]["months"][0]["met_target"] is False
    assert p["totals"]["years"][0]["by_withdrawer"][str(ws["M"])] == 96_700_000
    # upsert, not duplicate
    client.post(API + "/entries", json={"withdrawer_id": ws["N"], "year": 1405, "month": 1, "amount": 0})
    p = _get(client)
    assert len(p["entries"]) == 3
    eid = p["entries"][0]["id"]
    assert client.delete(f"{API}/entries/{eid}").status_code == 200
    assert len(_get(client)["entries"]) == 2
    assert client.post(API + "/entries", json={"withdrawer_id": ws["N"], "year": 1405, "month": 13, "amount": 1}).status_code == 400
    assert client.post(API + "/entries", json={"withdrawer_id": 999, "year": 1405, "month": 1, "amount": 1}).status_code == 404
    assert client.put(API + "/target", json={"target": "abc"}).status_code == 400


def test_withdrawers_add_rename_remove(client):
    _login(client, OWNER)
    p = client.post(API + "/withdrawers", json={"name": "  Z  "}).get_json()["pwo"]
    z = [w for w in p["withdrawers"] if w["name"] == "Z"][0]
    client.put(f"{API}/withdrawers/{z['id']}", json={"name": "Zed"})
    ids = {w["name"]: w["id"] for w in _get(client)["withdrawers"]}
    assert "Zed" in ids
    # with entries -> archived, entries kept
    client.post(API + "/entries", json={"withdrawer_id": ids["M"], "year": 1405, "month": 2, "amount": 5})
    client.delete(f"{API}/withdrawers/{ids['M']}")
    p = _get(client)
    m = [w for w in p["withdrawers"] if w["id"] == ids["M"]][0]
    assert m["archived"] is True and len(p["entries"]) == 1
    # without entries -> removed
    client.post(f"{API}/withdrawers/{ids['A']}/delete")
    client.delete(f"{API}/withdrawers/{ids['N']}")
    p = _get(client)
    assert [w["name"] for w in p["withdrawers"] if not w["archived"]] == ["Zed"]
    r = client.delete(f"{API}/withdrawers/{ids['Zed']}")
    assert r.status_code == 400 and r.get_json()["error"] == "last_withdrawer"
    assert client.post(API + "/withdrawers", json={"name": ""}).status_code == 400


def test_per_account_isolation(client):
    _login(client, OWNER)
    client.post(API + "/withdrawers", json={"name": "OnlyOwner"})
    client.put(API + "/target", json={"target": 5})
    _login(client, OTHER)
    p = _get(client)
    assert p["target"] == 100_000_000
    assert "OnlyOwner" not in [w["name"] for w in p["withdrawers"]]


def test_import_idempotent_and_no_overwrite(client):
    _login(client, OWNER)
    body = {"target": 100_000_000, "withdrawers": ["M", "A", "N"], "entries": [
        {"withdrawer": "M", "year": 1405, "month": 1, "amount": 96_700_000},
        {"withdrawer": "A", "year": 1405, "month": 1, "amount": 15_000_000},
        {"withdrawer": "Q", "year": 1405, "month": 1, "amount": 1}]}
    r = client.post(API + "/import", json=body).get_json()
    assert r["written"] == 3 and r["skipped"] == 0
    r = client.post(API + "/import", json=body).get_json()
    assert r["written"] == 0 and r["skipped"] == 3
    assert len(r["pwo"]["entries"]) == 3
    body["entries"][0]["amount"] = 1
    r = client.post(API + "/import", json=body).get_json()
    assert [e for e in r["pwo"]["entries"] if e["amount"] == 96_700_000]
    r = client.post(API + "/import", json={**body, "overwrite": True}).get_json()
    assert r["written"] == 3


def test_migration_keeps_existing_data(tmp_path):
    import sqlite3
    from invest_app.database.migrations import run_migrations
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO settings VALUES ('pwo_monthly_target','7')")
    conn.execute("CREATE TABLE capital_snapshots (date TEXT, total_value REAL, created_at TEXT)")
    run_migrations(conn)
    run_migrations(conn)
    assert conn.execute("SELECT value FROM settings WHERE key='pwo_monthly_target'").fetchone()[0] == "7"
    assert conn.execute("SELECT COUNT(*) FROM pwo_withdrawers").fetchone()[0] == 3
