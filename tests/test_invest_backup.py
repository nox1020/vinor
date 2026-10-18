# -*- coding: utf-8 -*-
"""The Invest backup download must not rewrite the live database files."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask

SECRET = "ci-only-not-secret"
PHONE = "09120001301"
PLANTED = "SECRET-VALUE-XYZ-999"
NOTE = "notes-secret-phrase"
_TEHRAN = ZoneInfo("Asia/Tehran")


def _stamp(path: Path):
    st = path.stat()
    return path.read_bytes(), st.st_mtime_ns


def _client(instance: Path, rate_file: Path):
    import os

    os.environ["VINOR_WEBHOOK_SECRET"] = SECRET
    os.environ["VINOR_INVEST_BACKUP_RATE_FILE"] = str(rate_file)
    app = Flask(__name__, instance_path=str(instance))
    app.config["TESTING"] = True
    from app.routes.public import healthz_invest_backup

    app.add_url_rule("/healthz/invest-backup", view_func=healthz_invest_backup)
    return app.test_client()


def test_backup_zip_leaves_source_bytes_and_mtime_unchanged(tmp_path, monkeypatch):
    instance = tmp_path / "instance"
    user = instance / "invest" / "users" / PHONE
    user.mkdir(parents=True)
    db_path = user / "invest.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO assets (name) VALUES (?)", (PLANTED,))
    conn.commit()
    note = user / "notes.txt"
    note.write_text(NOTE, encoding="utf-8")
    link_target = tmp_path / "outside.txt"
    link_target.write_text("do-not-follow", encoding="utf-8")
    (user / "linked.txt").symlink_to(link_target)

    bare = tmp_path / "bare.db"
    bare.write_bytes(db_path.read_bytes())
    bare_conn = sqlite3.connect(f"{bare.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    bare_names = [row[0] for row in bare_conn.execute("SELECT name FROM sqlite_master")]
    bare_conn.close()
    assert "assets" not in bare_names

    before = {
        path.name: _stamp(path)
        for path in user.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    names_before = sorted(p.name for p in user.iterdir())
    made = []
    real_mkdtemp = tempfile.mkdtemp

    def _track(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        made.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", _track)
    client = _client(instance, tmp_path / "rate")

    denied = client.get("/healthz/invest-backup")
    assert denied.status_code == 401
    assert denied.is_json
    assert denied.get_json() == {"ok": False}
    assert not (tmp_path / "rate").exists()

    response = client.get(
        "/healthz/invest-backup",
        headers={"X-Vinor-Otp-Diag": SECRET},
    )
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    body = response.get_data()
    response.close()
    today = datetime.now(_TEHRAN).strftime("%Y-%m-%d")
    disposition = response.headers["Content-Disposition"]
    assert f"invest-backup-{today}.zip" in disposition
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Backup-Users"] == "1"
    assert response.headers["X-Backup-Bytes"] == str(len(body))
    assert response.headers["X-Backup-Sha256"] == hashlib.sha256(body).hexdigest()

    after = {
        path.name: _stamp(path)
        for path in user.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    assert after == before
    assert sorted(p.name for p in user.iterdir()) == names_before
    assert _stamp(link_target)[0] == b"do-not-follow"

    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        manifests = [name for name in names if name.endswith("/manifest.json")]
        dbs = [name for name in names if name.endswith(f"/users/{PHONE}/invest.db")]
        notes = [name for name in names if name.endswith(f"/users/{PHONE}/notes.txt")]
        assert len(manifests) == 1
        assert len(dbs) == 1
        assert len(notes) == 1
        assert not any(name.endswith("-wal") or name.endswith("-shm") for name in names)
        assert not any("linked.txt" in name for name in names)
        root = manifests[0].split("/")[0]
        assert root.startswith(f"invest-backup-{today}_")
        assert dbs[0].startswith(root + "/")
        manifest = json.loads(archive.read(manifests[0]).decode("utf-8"))
        manifest_text = archive.read(manifests[0]).decode("utf-8")
        assert PLANTED not in manifest_text
        assert NOTE not in manifest_text
        assert manifest["user_count"] == 1
        entry = manifest["users"][0]
        assert entry["folder"] == PHONE
        assert entry["tables"]["assets"] == 1
        assert entry["db_bytes"] > 0
        assert "db_mtime" in entry
        assert entry["files"] == [
            {"name": "notes.txt", "bytes": len(NOTE.encode("utf-8")), "mtime": entry["files"][0]["mtime"]}
        ]
        assert "T" in entry["files"][0]["mtime"]
        snapshot = archive.read(dbs[0])
        assert archive.read(notes[0]) == NOTE.encode("utf-8")

    snap_path = tmp_path / "snap.db"
    snap_path.write_bytes(snapshot)
    snap = sqlite3.connect(f"{snap_path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        assert snap.execute("SELECT name FROM assets").fetchone()[0] == PLANTED
    finally:
        snap.close()

    limited = client.get(
        "/healthz/invest-backup",
        headers={"X-Vinor-Otp-Diag": SECRET},
    )
    assert limited.status_code == 429
    assert limited.is_json
    payload = limited.get_json()
    assert payload["error"] == "rate_limited"
    assert 1 <= payload["retry_after"] <= 600
    assert limited.headers["Retry-After"] == str(payload["retry_after"])

    work_dirs = [path for path in made if "vinor-invest-backup-" in path]
    assert work_dirs
    assert all(not Path(path).exists() for path in work_dirs)
    conn.close()


def test_guest_reaches_backup_without_the_landing_redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "instance"))
    monkeypatch.setenv("VINOR_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("VINOR_INVEST_BACKUP_RATE_FILE", str(tmp_path / "rate"))
    from app import create_app

    client = create_app().test_client()
    guest = client.get("/healthz/invest-backup", follow_redirects=False)
    assert guest.status_code == 401
    assert guest.is_json
    assert guest.get_json() == {"ok": False}
