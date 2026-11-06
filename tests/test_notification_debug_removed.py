# -*- coding: utf-8 -*-
"""The notification debug route listed every phone and rewrote storage on GET."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PHONES = ("09120000001", "09120000002")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-notif-debug")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    data = tmp_path / "data"
    data.mkdir()
    (data / "notifications.json").write_text(
        json.dumps({phone: [{"id": "1", "title": "t"}] for phone in PHONES}, ensure_ascii=False),
        encoding="utf-8",
    )
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _stored(app) -> dict:
    path = Path(app.instance_path) / "data" / "notifications.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("session_values", [
    {},
    {"user_phone": PHONES[0]},
    {"logged_in": True, "admin_phone": "09120000000"},
])
def test_debug_route_is_gone_and_does_not_rewrite_storage(client, app, session_values):
    before = _stored(app)
    if session_values:
        with client.session_transaction() as sess:
            sess.update(session_values)
    resp = client.get("/express/partner/api/notifications/debug")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    for phone in PHONES:
        assert phone not in body
    assert _stored(app) == before


def test_partner_notification_list_stays_available(client):
    with client.session_transaction() as sess:
        sess["user_phone"] = PHONES[0]
    resp = client.get("/express/partner/api/notifications")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert PHONES[1] not in text
