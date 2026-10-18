# -*- coding: utf-8 -*-
"""Read-only Invest inventory. The endpoint must not create files."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from flask import Flask

SECRET = "ci-only-not-secret"
PHONE = "09120000000"
FULL_VALUE = "SECRET-09120000000-amount-999999"


def _write_db(path: Path) -> None:
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE assets (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE checks (id INTEGER PRIMARY KEY, amount REAL);
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT);
        INSERT INTO settings (key, value) VALUES ('client_checks_synced', '1');
        INSERT INTO assets (id, name) VALUES (1, 'hidden');
        INSERT INTO trades (id, status) VALUES (1, 'open');
        INSERT INTO trades (id, status) VALUES (2, 'closed');
        INSERT INTO checks (id, amount) VALUES (1, 999999);
        INSERT INTO schema_migrations (version, applied_at) VALUES (4, 't');
        """
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('client_withdrawals', ?)",
        (FULL_VALUE,),
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('client_portfolio', ?)",
        (json.dumps([{"name": "hidden", "value": 999999}]),),
    )
    conn.commit()
    conn.close()
    # The diagnostic must not need the connection's wal mode.
    (path.parent / "invest_backup_20260101.db").write_bytes(b"backup-bytes")


def test_inventory_reports_sizes_without_values_or_creating_files(tmp_path, monkeypatch):
    instance = tmp_path / "instance"
    user = instance / "invest" / "users" / PHONE
    _write_db(user / "invest.db")
    profile = instance / "invest" / "profiles" / f"{PHONE}.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        json.dumps({"phone": PHONE, "name": "Masoud", "backup": [1, 2, 3]}),
        encoding="utf-8",
    )
    legacy = instance / "invest.db"
    legacy.write_bytes(b"legacy")
    before = sorted(p.relative_to(instance).as_posix() for p in instance.rglob("*"))

    monkeypatch.setenv("VINOR_WEBHOOK_SECRET", SECRET)
    app = Flask(__name__, instance_path=str(instance))
    app.config["TESTING"] = True
    from app.routes.public import healthz_invest_data

    app.add_url_rule("/healthz/invest-data", view_func=healthz_invest_data)
    client = app.test_client()

    denied = client.get("/healthz/invest-data")
    assert denied.status_code == 401
    bad = client.get(
        "/healthz/invest-data?phone_last4=12",
        headers={"X-Vinor-Otp-Diag": SECRET},
    )
    assert bad.status_code == 400

    response = client.get(
        "/healthz/invest-data?phone_last4=0000",
        headers={"X-Vinor-Otp-Diag": SECRET},
    )
    assert response.status_code == 200
    body = response.get_json()
    text = response.get_data(as_text=True)
    assert PHONE not in text
    assert "SECRET" not in text
    assert "999999" not in text
    assert "Masoud" not in text
    assert body["user_count"] == 1
    user_row = body["users"][0]
    assert user_row["phone_last4"] == "0000"
    assert user_row["folder_len"] == 11
    assert user_row["sqlite"]["counts"]["assets"] == 1
    assert user_row["sqlite"]["counts"]["trades"] == 2
    assert user_row["sqlite"]["counts"]["trades_open"] == 1
    assert user_row["sqlite"]["counts"]["trades_closed"] == 1
    assert user_row["sqlite"]["counts"]["checks"] == 1
    assert user_row["sqlite"]["schema_version"] == 4
    keys = {row["key"]: row for row in user_row["sqlite"]["settings_keys"]}
    assert keys["client_withdrawals"]["chars"] == len(FULL_VALUE)
    assert keys["client_portfolio"]["shape"] == "list"
    assert keys["client_portfolio"]["items"] == 1
    assert user_row["backup_files"][0]["name"] == "invest_backup_*****.db"
    assert user_row["backup_files"][0]["bytes"] == len(b"backup-bytes")
    profile_keys = {row["key"]: row for row in user_row["profile"]["keys"]}
    assert profile_keys["backup"]["shape"] == "list"
    assert profile_keys["backup"]["items"] == 3
    assert profile_keys["phone"]["chars"] == len(PHONE)
    legacy_row = next(row for row in body["legacy"] if row["label"] == "instance/invest.db")
    assert legacy_row["exists"] is True
    assert legacy_row["bytes"] == len(b"legacy")
    after = sorted(p.relative_to(instance).as_posix() for p in instance.rglob("*"))
    assert after == before


def test_missing_root_is_empty_and_not_created(tmp_path, monkeypatch):
    instance = tmp_path / "empty-instance"
    instance.mkdir()
    monkeypatch.setenv("VINOR_WEBHOOK_SECRET", SECRET)
    from invest.backend.data_diag import invest_data_report

    report = invest_data_report(instance, phone_last4="0000")
    assert report["invest_root_exists"] is False
    assert report["users"] == []
    assert not (instance / "invest").exists()
    assert os.environ["VINOR_WEBHOOK_SECRET"] == SECRET
