# -*- coding: utf-8 -*-
"""دفتر چک Invest: اعتبار، وضعیت، سررسید، و آینهٔ تنظیمات."""
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


def _today():
    from invest_app.services.check_service import tehran_today

    return tehran_today()


def _payload(**overrides):
    today = _today()
    body = {
        "direction": "receivable",
        "amount": "۱٬۵۰۰٬۰۰۰",
        "issue_date": "1404/01/01",
        "due_date": (today + timedelta(days=3)).isoformat(),
        "check_number": "",
        "sayad_id": "۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶",
        "bank_name": "ملت",
        "counterparty": "علی رضایی",
        "purpose": "بیعانه",
    }
    body.update(overrides)
    return body


def test_checks_require_login_and_accept_session_token(client, app):
    guest = client.post("/invest/api/v1/checks", json=_payload())
    assert guest.status_code == 401
    assert guest.get_json()["error"] == "auth_required"
    assert guest.get_json()["success"] is False

    _login(client, OWNER)
    created = client.post("/invest/api/v1/checks", json=_payload())
    assert created.status_code == 200
    cookie = client.get_cookie("vinor_session")
    assert cookie is not None
    bare = app.test_client()
    authed = bare.get(
        "/invest/api/v1/checks",
        headers={"Authorization": f"Bearer {cookie.value}"},
    )
    assert authed.status_code == 200
    assert authed.get_json()["count"] == 1
    rejected = bare.get(
        "/invest/api/v1/checks",
        headers={"Authorization": "Bearer not-a-session"},
    )
    assert rejected.status_code == 401


def test_create_list_update_delete_and_jalali_amount(client):
    _login(client, OWNER)
    created = client.post("/invest/api/v1/checks", json=_payload())
    assert created.status_code == 200
    item = created.get_json()["item"]
    assert item["direction"] == "receivable"
    assert item["amount"] == 1_500_000
    assert item["issue_date"] == "2025-03-21"
    assert item["issue_date_jalali"] == "1404/01/01"
    assert item["sayad_id"] == "1234567890123456"
    assert item["status"] == "pending"
    assert item["status_label"] == "نزد صندوق"
    assert item["settled_date"] is None
    assert item["days_until_due"] == 3
    assert item["is_open"] is True

    listed = client.get("/invest/api/v1/checks").get_json()
    assert listed["summary"]["open_receivable"] == 1_500_000
    assert listed["summary"]["net"] == 1_500_000
    assert listed["summary"]["due_soon_count"] == 1

    cleared = client.patch(
        f"/invest/api/v1/checks/{item['id']}",
        json={"status": "cleared"},
    )
    assert cleared.status_code == 200
    done = cleared.get_json()["item"]
    assert done["status"] == "cleared"
    assert done["status_label"] == "وصول شده"
    assert done["settled_date"] == _today().isoformat()
    assert done["is_open"] is False

    illegal = client.patch(
        f"/invest/api/v1/checks/{item['id']}",
        json={"status": "endorsed"},
    )
    assert illegal.status_code == 400
    assert illegal.get_json()["error"] == "validation"
    assert "مجاز نیست" in illegal.get_json()["message"]

    missing = client.delete("/invest/api/v1/checks/999999")
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "not_found"
    removed = client.post(f"/invest/api/v1/checks/{item['id']}/delete")
    assert removed.status_code == 200
    assert removed.get_json()["deleted"] is True
    assert client.get("/invest/api/v1/checks").get_json()["items"] == []


def test_validation_duplicates_transitions_and_isolation(client):
    _login(client, OWNER)
    first = client.post("/invest/api/v1/checks", json=_payload()).get_json()["item"]
    again = client.post("/invest/api/v1/checks", json=_payload())
    assert again.status_code == 409
    assert again.get_json()["error"] == "conflict"

    payable = client.post("/invest/api/v1/checks", json=_payload(
        direction="payable",
        sayad_id="2222222222222222",
        status="endorsed",
    ))
    assert payable.status_code == 400
    assert "پرداختی" in payable.get_json()["message"]

    early = client.post("/invest/api/v1/checks", json=_payload(
        sayad_id="3333333333333333",
        issue_date="1404/03/01",
        due_date="1404/01/01",
    ))
    assert early.status_code == 400

    short = client.post("/invest/api/v1/checks", json=_payload(sayad_id="1234"))
    assert short.status_code == 400

    same_number = client.post("/invest/api/v1/checks", json=_payload(
        sayad_id="",
        check_number="44",
        bank_name="ملت",
    ))
    assert same_number.status_code == 200
    twin = client.post("/invest/api/v1/checks", json=_payload(
        sayad_id="",
        check_number="۴۴",
        bank_name="ملت",
    ))
    assert twin.status_code == 409

    bounced = client.patch(
        f"/invest/api/v1/checks/{first['id']}",
        json={"status": "bounced"},
    )
    assert bounced.status_code == 200
    no_endorse = client.patch(
        f"/invest/api/v1/checks/{first['id']}",
        json={"status": "endorsed"},
    )
    assert no_endorse.status_code == 400
    restored = client.patch(
        f"/invest/api/v1/checks/{first['id']}",
        json={"status": "pending"},
    )
    assert restored.status_code == 200
    duplicate_id = client.post("/invest/api/v1/checks", json=_payload(
        id=first["id"],
        sayad_id="8888888888888888",
    ))
    assert duplicate_id.status_code == 409
    assert duplicate_id.get_json()["message"] == "شناسه چک تکراری است."

    cancelled = client.patch(
        f"/invest/api/v1/checks/{first['id']}",
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200
    reused = client.post("/invest/api/v1/checks", json=_payload())
    assert reused.status_code == 200

    _login(client, OTHER)
    assert client.get("/invest/api/v1/checks").get_json()["items"] == []
    foreign = client.patch(f"/invest/api/v1/checks/{first['id']}", json={"note": "نه"})
    assert foreign.status_code == 404


def test_reminders_and_settings_mirror(client):
    _login(client, OWNER)
    before = client.get("/invest/api/v1/settings").get_json()["settings"]
    assert "client_checks" not in before

    today = _today()
    overdue = client.post("/invest/api/v1/checks", json=_payload(
        sayad_id="4444444444444444",
        due_date=(today - timedelta(days=2)).isoformat(),
        issue_date=(today - timedelta(days=10)).isoformat(),
    )).get_json()["item"]
    soon = client.post("/invest/api/v1/checks", json=_payload(
        sayad_id="5555555555555555",
        due_date=(today + timedelta(days=1)).isoformat(),
    )).get_json()["item"]
    bounced = client.post("/invest/api/v1/checks", json=_payload(
        direction="payable",
        sayad_id="6666666666666666",
        check_number="9",
        due_date=(today + timedelta(days=20)).isoformat(),
    )).get_json()["item"]
    bounced = client.patch(
        f"/invest/api/v1/checks/{bounced['id']}",
        json={"status": "bounced"},
    ).get_json()["item"]
    assert bounced["status_label"] == "برگشتی"
    assert bounced["counts_as_debt"] is True

    reminders = client.get("/invest/api/v1/checks/reminders?within_days=7").get_json()
    overdue_ids = {item["id"] for item in reminders["overdue"]}
    soon_ids = {item["id"] for item in reminders["due_soon"]}
    bounced_ids = {item["id"] for item in reminders["bounced"]}
    assert overdue["id"] in overdue_ids
    assert soon["id"] in soon_ids
    assert bounced["id"] in bounced_ids
    assert overdue["due_label"].endswith("گذشته") or "دیروز" in overdue["due_label"]

    cors = client.get(
        "/invest/api/v1/checks",
        headers={"Origin": "http://localhost:7357"},
    )
    # flask-cors echoes the request Origin when the resource allows "*".
    assert cors.headers.get("Access-Control-Allow-Origin") == "http://localhost:7357"
    assert cors.headers.get("Access-Control-Allow-Credentials") == "true"
    preflight = client.options(
        "/invest/api/v1/checks",
        headers={
            "Origin": "http://localhost:7357",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, Authorization",
        },
    )
    assert preflight.status_code in (200, 204)
    allowed = (preflight.headers.get("Access-Control-Allow-Headers") or "").lower()
    assert "authorization" in allowed
    assert "content-type" in allowed

    bad_window = client.get("/invest/api/v1/checks/reminders?within_days=no")
    assert bad_window.status_code == 400
    assert bad_window.get_json()["error"] == "validation"

    mirrored = client.put(
        "/invest/api/v1/settings",
        json={
            "client_checks": [{
                "id": 88001,
                "direction": "receivable",
                "amount": 250000,
                "issue_date": "1404-01-15",
                "due_date": "1404-02-01",
                "sayad_id": "7777777777777777",
                "status": "pending",
            }],
        },
    )
    assert mirrored.status_code == 200
    echoed = mirrored.get_json()["settings"]["client_checks"]
    assert [row["id"] for row in echoed] == [88001]
    assert echoed[0]["issue_date"] == "2025-04-04"
    fetched = client.get("/invest/api/v1/settings").get_json()["settings"]["client_checks"]
    assert [row["id"] for row in fetched] == [88001]

    bad = client.put(
        "/invest/api/v1/settings",
        json={"theme": "dark", "client_checks": [{"id": 88002, "amount": 0}]},
    )
    assert bad.status_code == 200
    body = bad.get_json()["settings"]
    assert body["theme"] == "dark"
    assert body["client_checks_error"]["error"] == "validation"
    assert [row["id"] for row in body["client_checks"]] == [88001]


def test_archive_hides_from_totals_and_reminders_and_restores(client):
    _login(client, OWNER)
    item = client.post("/invest/api/v1/checks", json=_payload()).get_json()["item"]
    assert item["is_archived"] is False and item["archived_at"] is None

    archived = client.patch(f"/invest/api/v1/checks/{item['id']}", json={"archived": True})
    assert archived.status_code == 200
    row = archived.get_json()["item"]
    assert row["is_archived"] is True and row["archived_at"]
    assert row["status"] == "pending"
    assert row["counts_as_receivable"] is False

    listed = client.get("/invest/api/v1/checks").get_json()
    assert listed["count"] == 1  # data is kept
    assert listed["summary"]["open_receivable"] == 0
    assert listed["summary"]["due_soon_count"] == 0
    assert client.get("/invest/api/v1/checks?archived=exclude").get_json()["items"] == []
    assert len(client.get("/invest/api/v1/checks?archived=only").get_json()["items"]) == 1
    assert client.get("/invest/api/v1/checks/reminders").get_json()["items"] == []

    # An older client that omits the field keeps the archive flag.
    kept = client.patch(f"/invest/api/v1/checks/{item['id']}", json={"note": "x"}).get_json()["item"]
    assert kept["archived_at"] == row["archived_at"]

    restored = client.patch(f"/invest/api/v1/checks/{item['id']}", json={"archived": False}).get_json()["item"]
    assert restored["is_archived"] is False
    assert client.get("/invest/api/v1/checks").get_json()["summary"]["open_receivable"] == 1_500_000


def test_migration_9_adds_archived_column_without_touching_rows(tmp_path):
    import sqlite3

    from invest_app.database.migrations import _migrate_9

    conn = sqlite3.connect(tmp_path / "old.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE checks (id INTEGER PRIMARY KEY, direction TEXT, amount REAL, status TEXT,"
        " settled_date TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute("INSERT INTO checks VALUES (1, 'payable', 5, 'pending', NULL, 'a', 'b')")
    _migrate_9(conn)
    _migrate_9(conn)  # idempotent
    row = dict(conn.execute("SELECT * FROM checks").fetchone())
    assert row["archived_at"] is None
    assert row["amount"] == 5 and row["updated_at"] == "b"
