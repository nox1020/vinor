# -*- coding: utf-8 -*-
"""Invest projects / پیمانکاری."""
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



P = "/invest/api/v1/projects"


def _sheet():
    return {"projects": [
        {"start_date": "1404/01/01", "end_date": "1404/01/30", "contract_amount": "85,000,000",
         "cost": 39025000, "description": "کارفرما الف - دیوارکشی"},
        {"start_date": "1404/09/30", "end_date": "10/04/1405", "contract_amount": 199000000,
         "cost": 219599000, "description": "کارفرما ب - دیوار کشی"},
        {"description": "کارفرما ج"},
    ]}


def test_projects_crud_totals_import_archive_and_isolation(client):
    _login(client, OWNER)
    empty = client.get(P).get_json()["projects"]
    assert empty["items"] == [] and empty["totals"]["realized_profit"] == 0

    r = client.post(f"{P}/import", json=_sheet()).get_json()
    assert r["written"] == 3 and r["skipped"] == 0
    snap = r["projects"]
    a, b, c = snap["items"][0], snap["items"][1], snap["items"][2]
    assert a["title"] == "کارفرما الف" and a["work_type"] == "دیوارکشی"
    assert a["profit"] == 45975000 and round(a["profit_pct"]) == 54
    assert a["status"] == "finished" and a["days"] == 29
    assert b["end_date"] == "1405/04/10" and b["profit"] == -20599000
    assert c["status"] == "pipeline" and c["profit"] is None
    t = snap["totals"]
    assert t["realized_profit"] == 45975000 - 20599000
    assert t["pipeline_count"] == 1 and t["finished_count"] == 2

    again = client.post(f"{P}/import", json=_sheet()).get_json()
    assert again["written"] == 0 and again["skipped"] == 3

    # in-progress: future end ⇒ expected, not realized
    add = client.post(P, json={"title": "کارفرما د", "start_date": "1405/07/01",
                               "end_date": "1499/01/01", "contract_amount": 100, "cost": 40},
                      headers={"Idempotency-Key": "k-proj-1"}).get_json()["projects"]
    d = [p for p in add["items"] if p["title"] == "کارفرما د"][0]
    assert d["status"] == "active"
    assert add["totals"]["expected_profit"] == 60
    assert add["totals"]["realized_profit"] == t["realized_profit"]
    replay = client.post(P, json={"title": "کارفرما د"}, headers={"Idempotency-Key": "k-proj-1"})
    assert replay.get_json()["replayed"] is True
    assert len(replay.get_json()["projects"]["items"]) == 4

    bad = client.patch(f"{P}/{d['id']}", json={"end_date": "1405/01/01"})
    assert bad.status_code == 400
    done = client.patch(f"{P}/{d['id']}", json={"status_mode": "finished"}).get_json()["projects"]
    assert done["totals"]["realized_profit"] == t["realized_profit"] + 60

    arch = client.patch(f"{P}/{a['id']}", json={"archived": True}).get_json()["projects"]
    row = [p for p in arch["items"] if p["id"] == a["id"]][0]
    assert row["archived"] is True and row["profit"] == 45975000
    assert arch["totals"]["archived_count"] == 1
    assert arch["totals"]["realized_profit"] == t["realized_profit"] + 60 - 45975000
    note = client.patch(f"{P}/{a['id']}", json={"note": "x"}).get_json()["projects"]
    assert [p for p in note["items"] if p["id"] == a["id"]][0]["archived"] is True

    exp = client.get(f"{P}/export").get_json()["export"]["projects"]
    assert len(exp) == 4 and any(p["archived"] for p in exp)

    assert client.post(f"{P}/{c['id']}/delete").status_code == 200
    assert client.delete(f"{P}/999999").status_code == 404

    _login(client, OTHER)
    assert client.get(P).get_json()["projects"]["items"] == []


def test_project_validation(client):
    _login(client, OWNER)
    assert client.post(P, json={"title": ""}).status_code == 400
    assert client.post(P, json={"title": "x", "status_mode": "finished"}).status_code == 400
    assert client.post(P, json={"title": "x", "start_date": "1405/13/01"}).status_code == 400
    assert client.post(P, json={"title": "x", "contract_amount": "-5"}).status_code == 400
    r = client.post(f"{P}/import", json={"projects": [{"description": ""}]})
    assert r.status_code == 400 and "ردیف 1" in r.get_json()["message"]
    assert client.get(P).get_json()["projects"]["items"] == []


def test_migration_10_is_additive(tmp_path):
    import sqlite3

    from invest_app.database.migrations import _migrate_10

    conn = sqlite3.connect(tmp_path / "x.db")
    conn.execute("CREATE TABLE biz_property_trades (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO biz_property_trades VALUES (1, 'keep')")
    _migrate_10(conn)
    _migrate_10(conn)
    assert conn.execute("SELECT title FROM biz_property_trades").fetchall() == [("keep",)]
    assert conn.execute("SELECT COUNT(*) FROM biz_projects").fetchone()[0] == 0
