# -*- coding: utf-8 -*-
"""POST /api/uploads/images requires a logged-in session. Existing files stay public."""
from __future__ import annotations

import io
import struct
import zlib

import pytest


def _png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"\x00\xff\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-upload-auth")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True, UPLOAD_FOLDER=str(tmp_path / "uploads"))
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _csrf(client) -> dict:
    client.get("/express/partner/login")
    cookie = client.get_cookie("XSRF-TOKEN")
    token = getattr(cookie, "value", cookie)
    assert token
    return {"X-CSRFToken": token}


def _post(client, headers):
    return client.post(
        "/api/uploads/images",
        data={"file": (io.BytesIO(_png()), "dot.png")},
        content_type="multipart/form-data",
        headers=headers,
    )


def test_anonymous_upload_is_rejected_even_with_csrf(client):
    missing = _post(client, {})
    assert missing.status_code in (302, 400, 401)
    denied = _post(client, _csrf(client))
    assert denied.status_code == 401
    assert denied.get_json()["error"] == "unauthorized"


def test_logged_in_user_can_upload_and_the_file_stays_readable(client):
    with client.session_transaction() as sess:
        sess["user_phone"] = "09120000000"
    resp = _post(client, _csrf(client))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["url"].startswith("/uploads/")
    fetched = client.get(body["url"])
    assert fetched.status_code == 200
    assert fetched.data[:8] == b"\x89PNG\r\n\x1a\n"
