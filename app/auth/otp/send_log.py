# -*- coding: utf-8 -*-
"""Last OTP gateway attempts. Phone is last-4 only. The code is never stored."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

_LOCK = threading.Lock()
_KEEP = 30
_SCHEMA = """
CREATE TABLE IF NOT EXISTS otp_send_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    phone_last4 TEXT NOT NULL,
    http_status INTEGER,
    path TEXT NOT NULL,
    duration_ms INTEGER,
    gateway_status TEXT,
    gateway_message TEXT,
    message_id TEXT,
    body_json TEXT
);
"""


def _connect() -> sqlite3.Connection:
    from .store import db_path

    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def scrub_text(text: str, *, code: str = "", phone: str = "") -> str:
    raw = str(text or "")
    if code:
        raw = raw.replace(str(code), "*****")
    if phone:
        raw = raw.replace(str(phone), "09*****")
        if str(phone).startswith("0") and len(phone) > 1:
            raw = raw.replace(str(phone)[1:], "9*****")
    raw = re.sub(r"(?:\+98|0098|98|0)?9\d{9}", "09*****", raw)
    raw = re.sub(r"\d{4,}", "*****", raw)
    return raw


def _message_id(body: dict) -> str:
    data = body.get("data")
    candidates = []
    if isinstance(data, dict):
        candidates.extend([data.get("messageId"), data.get("message_id"), data.get("MessageId")])
    candidates.extend([body.get("messageId"), body.get("message_id")])
    for item in candidates:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            return text[:80]
    return ""


def _gateway_message(body: dict) -> str:
    for key in ("message", "Message", "error", "Error", "title", "detail"):
        val = body.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    raw = body.get("raw")
    if raw is not None and str(raw).strip():
        return str(raw).strip()[:300]
    return ""


def summarize_attempt(
    *,
    phone: str,
    http_status: object,
    path: str,
    duration_ms: int,
    body: object,
    code: str = "",
) -> dict:
    payload = body if isinstance(body, dict) else {"raw": "" if body is None else str(body)[:500]}
    message_id = _message_id(payload)
    if code and message_id == str(code):
        message_id = "*****"
    try:
        http = int(http_status) if http_status is not None else 0
    except (TypeError, ValueError):
        http = 0
    status = payload.get("status")
    status_text = "" if status is None else str(status)[:40]
    return {
        "path": path,
        "http": http,
        "status": status if isinstance(status, int) else status_text or None,
        "message": scrub_text(_gateway_message(payload), code=code, phone=phone)[:300],
        "message_id": scrub_text(message_id, code=code, phone=phone)[:80],
        "duration_ms": int(duration_ms),
        "phone_last4": (str(phone or "")[-4:] if phone else ""),
        "body_json": scrub_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            code=code,
            phone=phone,
        )[:2000],
    }


def record_attempt(view: dict) -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO otp_send_attempts (
                    ts, phone_last4, http_status, path, duration_ms,
                    gateway_status, gateway_message, message_id, body_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    str(view.get("phone_last4") or "")[-4:],
                    view.get("http"),
                    str(view.get("path") or "")[:40],
                    int(view.get("duration_ms") or 0),
                    "" if view.get("status") is None else str(view.get("status"))[:40],
                    str(view.get("message") or "")[:300],
                    str(view.get("message_id") or "")[:80],
                    str(view.get("body_json") or "")[:2000],
                ),
            )
            conn.execute(
                """
                DELETE FROM otp_send_attempts
                WHERE id NOT IN (
                    SELECT id FROM otp_send_attempts ORDER BY id DESC LIMIT ?
                )
                """,
                (_KEEP,),
            )
        finally:
            conn.close()


def recent_attempts(limit: int = _KEEP) -> list[dict]:
    cap = max(1, min(int(limit or _KEEP), _KEEP))
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT ts, phone_last4, http_status, path, duration_ms,
                       gateway_status, gateway_message, message_id, body_json
                FROM otp_send_attempts
                ORDER BY id DESC
                LIMIT ?
                """,
                (cap,),
            ).fetchall()
        finally:
            conn.close()
    out = []
    for row in rows:
        out.append(
            {
                "ts": row["ts"],
                "phone_last4": row["phone_last4"],
                "http": row["http_status"],
                "path": row["path"],
                "duration_ms": row["duration_ms"],
                "status": row["gateway_status"],
                "message": row["gateway_message"],
                "message_id": row["message_id"],
                "body": row["body_json"],
            }
        )
    return out


def public_attempt(view: dict) -> dict:
    return {
        "path": view.get("path"),
        "http": view.get("http"),
        "status": view.get("status"),
        "message": view.get("message"),
        "message_id": view.get("message_id"),
        "duration_ms": view.get("duration_ms"),
    }


def fetch_sms_ir_account() -> dict:
    """Credit and lines from sms.ir. The API key is not included."""
    import requests

    from app.utils.secrets import get_sms_api_key

    key = (get_sms_api_key() or "").strip()
    if not key:
        return {"credit": {"http": 0, "body": {"error": "missing_api_key"}}, "lines": None}
    headers = {"Accept": "application/json", "x-api-key": key}
    out: dict = {}
    for name, url in (
        ("credit", "https://api.sms.ir/v1/credit"),
        ("lines", "https://api.sms.ir/v1/line"),
    ):
        try:
            resp = requests.get(url, headers=headers, timeout=(3.05, 8))
            content_type = (resp.headers.get("content-type") or "").lower()
            if content_type.startswith("application/json"):
                body = resp.json()
            else:
                body = {"raw": scrub_text(resp.text)[:500]}
            out[name] = {"http": resp.status_code, "body": body}
        except Exception as exc:
            out[name] = {"http": 0, "body": {"error": type(exc).__name__}}
    return out
