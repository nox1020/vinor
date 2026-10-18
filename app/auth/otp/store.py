# -*- coding: utf-8 -*-
"""SQLite OTP challenge store — hashed codes only, atomic verify."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from typing import Any

from app.utils.storage import data_dir

from .config import otp_max_attempts, otp_retain_days, otp_ttl_seconds
from .crypto import hash_otp, verify_otp_hash

STATUS_REQUESTED = "REQUESTED"
STATUS_SENT = "SENT"
STATUS_PENDING = "PENDING"
STATUS_VERIFIED = "VERIFIED"
STATUS_EXPIRED = "EXPIRED"
STATUS_USED = "USED"
STATUS_LOCKED = "LOCKED"
STATUS_DELIVERY_FAILED = "DELIVERY_FAILED"
STATUS_SUPERSEDED = "SUPERSEDED"

_LOCK = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS otp_challenges (
    id TEXT PRIMARY KEY,
    phone TEXT NOT NULL,
    purpose TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used_at REAL,
    created_at REAL NOT NULL,
    last_sent_at REAL,
    provider TEXT,
    request_id TEXT,
    ip_hash TEXT,
    ua_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_otp_phone_purpose ON otp_challenges(phone, purpose, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_otp_expires ON otp_challenges(expires_at);
CREATE TABLE IF NOT EXISTS otp_rate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_rate ON otp_rate_events(kind, key_hash, ts);
"""


def db_path() -> str:
    return os.path.join(data_dir(), "otp_challenges.sqlite")


def _connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def init_schema() -> str:
    with _LOCK:
        conn = _connect()
        try:
            _purge_old_unlocked(conn)
            return db_path()
        finally:
            conn.close()


def purge_old_challenges(*, retain_days: int | None = None) -> int:
    """Delete OTP rows older than retain_days (default 7). Rate events older than 1h."""
    days = otp_retain_days() if retain_days is None else retain_days
    with _LOCK:
        conn = _connect()
        try:
            return _purge_old_unlocked(conn, retain_days=days)
        finally:
            conn.close()


def _purge_old_unlocked(conn: sqlite3.Connection, *, retain_days: int | None = None) -> int:
    days = otp_retain_days() if retain_days is None else retain_days
    cutoff = time.time() - max(1, days) * 86400
    hour_ago = time.time() - 3600
    cur = conn.execute("DELETE FROM otp_challenges WHERE created_at < ?", (cutoff,))
    deleted = int(cur.rowcount or 0)
    conn.execute("DELETE FROM otp_rate_events WHERE ts < ?", (hour_ago,))
    return deleted


def drop_schema() -> None:
    """Test/rollback helper — deletes the OTP sqlite file."""
    with _LOCK:
        path = db_path()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def create_challenge(
    *,
    phone: str,
    purpose: str,
    code: str,
    ip_hash: str = "",
    ua_hash: str = "",
    request_id: str = "",
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    now = time.time()
    ttl = otp_ttl_seconds() if ttl_seconds is None else ttl_seconds
    cid = str(uuid.uuid4())
    rec = {
        "id": cid,
        "phone": phone,
        "purpose": purpose,
        "code_hash": hash_otp(phone, purpose, code),
        "status": STATUS_REQUESTED,
        "expires_at": now + ttl,
        "attempts": 0,
        "used_at": None,
        "created_at": now,
        "last_sent_at": now,
        "provider": "",
        "request_id": request_id,
        "ip_hash": ip_hash,
        "ua_hash": ua_hash,
    }
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE otp_challenges
                SET status=?
                WHERE phone=? AND purpose=? AND used_at IS NULL
                  AND status IN (?, ?, ?, ?)
                """,
                (
                    STATUS_SUPERSEDED,
                    phone,
                    purpose,
                    STATUS_REQUESTED,
                    STATUS_SENT,
                    STATUS_PENDING,
                    STATUS_DELIVERY_FAILED,
                ),
            )
            conn.execute(
                """
                INSERT INTO otp_challenges (
                    id, phone, purpose, code_hash, status, expires_at, attempts,
                    used_at, created_at, last_sent_at, provider, request_id, ip_hash, ua_hash
                ) VALUES (
                    :id, :phone, :purpose, :code_hash, :status, :expires_at, :attempts,
                    :used_at, :created_at, :last_sent_at, :provider, :request_id, :ip_hash, :ua_hash
                )
                """,
                rec,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    return rec


def invalidate_active(phone: str, purpose: str) -> int:
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                UPDATE otp_challenges
                SET status=?
                WHERE phone=? AND purpose=? AND used_at IS NULL
                  AND status IN (?, ?, ?, ?)
                """,
                (
                    STATUS_SUPERSEDED,
                    phone,
                    purpose,
                    STATUS_REQUESTED,
                    STATUS_SENT,
                    STATUS_PENDING,
                    STATUS_DELIVERY_FAILED,
                ),
            )
            return int(cur.rowcount or 0)
        finally:
            conn.close()


def mark_delivery(
    challenge_id: str,
    *,
    provider: str,
    success: bool,
    request_id: str = "",
    count_as_sent: bool = False,
) -> None:
    """count_as_sent is for timeouts: the gateway may already have accepted the SMS."""
    accepted = bool(success or count_as_sent)
    status = STATUS_PENDING if accepted else STATUS_DELIVERY_FAILED
    sent_at = time.time() if accepted else None
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE otp_challenges
                SET status=?, provider=?, request_id=COALESCE(NULLIF(?, ''), request_id),
                    last_sent_at=?
                WHERE id=? AND used_at IS NULL
                """,
                (status, provider, request_id, sent_at, challenge_id),
            )
        finally:
            conn.close()


def active_challenge(phone: str, purpose: str) -> dict[str, Any] | None:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM otp_challenges
                WHERE phone=? AND purpose=? AND used_at IS NULL
                  AND status IN (?, ?, ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (phone, purpose, STATUS_REQUESTED, STATUS_SENT, STATUS_PENDING),
            ).fetchone()
            return _row_dict(row)
        finally:
            conn.close()


_SENT_STATUSES = (
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_VERIFIED,
    STATUS_USED,
    STATUS_EXPIRED,
    STATUS_LOCKED,
)


def last_sent_at(phone: str, purpose: str) -> float:
    """آخرین ارسالی که درگاه قبول کرده. رد قطعی و ردیف ناتمام کول‌داون نمی‌سازند."""
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT last_sent_at, created_at FROM otp_challenges
                WHERE phone=? AND purpose=? AND status IN (?, ?, ?, ?, ?, ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (phone, purpose, *_SENT_STATUSES),
            ).fetchone()
            rec = _row_dict(row)
        finally:
            conn.close()
    if not rec:
        return 0.0
    try:
        return float(rec.get("last_sent_at") or rec.get("created_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def record_rate_event(kind: str, key_hash: str) -> None:
    now = time.time()
    cutoff = now - 3600
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM otp_rate_events WHERE ts < ?",
                (cutoff,),
            )
            conn.execute(
                "INSERT INTO otp_rate_events (kind, key_hash, ts) VALUES (?, ?, ?)",
                (kind, key_hash, now),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def count_rate_events(kind: str, key_hash: str, *, since: float) -> int:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM otp_rate_events WHERE kind=? AND key_hash=? AND ts >= ?",
                (kind, key_hash, since),
            ).fetchone()
            return int(row["n"] if row else 0)
        finally:
            conn.close()


def consume_challenge(
    *,
    phone: str,
    purpose: str,
    code: str,
) -> tuple[str, dict[str, Any] | None]:
    """
    Atomically verify and consume an OTP.
    Returns (status_or_ok, record).
    'ok' means VERIFIED and consumed.
    """
    from .errors import (
        OTP_ALREADY_USED,
        OTP_EXPIRED,
        OTP_INVALID,
        OTP_TOO_MANY_ATTEMPTS,
    )

    now = time.time()
    dummy_phone = phone or "0"
    max_attempts = otp_max_attempts()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM otp_challenges
                WHERE phone=? AND purpose=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (phone, purpose),
            ).fetchone()
            rec = _row_dict(row)
            if rec is None:
                verify_otp_hash(dummy_phone, purpose, code or "000000", "0" * 64)
                conn.execute("COMMIT")
                return OTP_INVALID, None

            status = str(rec.get("status") or "")
            used_at = rec.get("used_at")
            expires_at = float(rec.get("expires_at") or 0)
            attempts = int(rec.get("attempts") or 0)

            if used_at or status == STATUS_VERIFIED:
                conn.execute(
                    "UPDATE otp_challenges SET status=? WHERE id=?",
                    (STATUS_USED, rec["id"]),
                )
                conn.execute("COMMIT")
                return OTP_ALREADY_USED, rec

            if status == STATUS_SUPERSEDED:
                conn.execute("COMMIT")
                return OTP_INVALID, rec

            if status == STATUS_LOCKED or attempts >= max_attempts:
                conn.execute(
                    "UPDATE otp_challenges SET status=? WHERE id=?",
                    (STATUS_LOCKED, rec["id"]),
                )
                conn.execute("COMMIT")
                return OTP_TOO_MANY_ATTEMPTS, rec

            if now > expires_at or status == STATUS_EXPIRED:
                conn.execute(
                    "UPDATE otp_challenges SET status=? WHERE id=?",
                    (STATUS_EXPIRED, rec["id"]),
                )
                conn.execute("COMMIT")
                return OTP_EXPIRED, rec

            matched = verify_otp_hash(phone, purpose, code, str(rec.get("code_hash") or ""))
            if not matched:
                attempts += 1
                new_status = STATUS_LOCKED if attempts >= max_attempts else STATUS_PENDING
                conn.execute(
                    "UPDATE otp_challenges SET attempts=?, status=? WHERE id=?",
                    (attempts, new_status, rec["id"]),
                )
                conn.execute("COMMIT")
                rec["attempts"] = attempts
                rec["status"] = new_status
                if new_status == STATUS_LOCKED:
                    return OTP_TOO_MANY_ATTEMPTS, rec
                return OTP_INVALID, rec

            conn.execute(
                """
                UPDATE otp_challenges
                SET used_at=?, status=?, attempts=attempts
                WHERE id=? AND used_at IS NULL
                """,
                (now, STATUS_VERIFIED, rec["id"]),
            )
            changed = conn.execute("SELECT changes() AS n").fetchone()
            conn.execute("COMMIT")
            if not changed or int(changed["n"] or 0) < 1:
                return OTP_ALREADY_USED, rec
            rec["used_at"] = now
            rec["status"] = STATUS_VERIFIED
            return "ok", rec
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()
