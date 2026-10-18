# -*- coding: utf-8 -*-
"""Read-only zip of Invest user databases. The live files are only read."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BACKUP_INTERVAL_SECONDS = 600
_RATE_LOCK = threading.Lock()
_TEHRAN = ZoneInfo("Asia/Tehran")
_SKIP_NAMES = {"invest.db", "invest.db-wal", "invest.db-shm"}
_SAFE_TABLE = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _rate_path() -> Path:
    override = (os.environ.get("VINOR_INVEST_BACKUP_RATE_FILE") or "").strip()
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "vinor-invest-backup.rate"


def reset_backup_rate_limit() -> None:
    with _RATE_LOCK:
        try:
            _rate_path().unlink()
        except OSError:
            pass


def reserve_backup_slot() -> tuple[bool, int]:
    """One successful reservation per interval. Returns (allowed, retry_after)."""
    now = time.time()
    path = _rate_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _RATE_LOCK:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                last = float(os.read(fd, 64).decode() or "0")
            except ValueError:
                last = 0.0
            wait = int(BACKUP_INTERVAL_SECONDS - (now - last))
            if last and wait > 0:
                return False, max(1, wait)
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, str(now).encode())
            return True, 0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=_TEHRAN).isoformat(timespec="seconds")


def _snapshot_db(src: Path, dest: Path) -> None:
    """Consistent copy via the sqlite backup API. Source is never opened."""
    hold = tempfile.TemporaryDirectory(prefix="vinor-bak-src-")
    try:
        copied = Path(hold.name) / "src.db"
        copied.write_bytes(src.read_bytes())
        for suffix in ("-wal", "-shm"):
            side = Path(str(src) + suffix)
            if side.is_file():
                Path(str(copied) + suffix).write_bytes(side.read_bytes())
        source = sqlite3.connect(f"{copied.resolve().as_uri()}?mode=ro", uri=True)
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    finally:
        hold.cleanup()


def _table_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(
        f"{db_path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    )
    try:
        names = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if _SAFE_TABLE.fullmatch(str(row[0] or ""))
        ]
        counts = {}
        for name in names:
            row = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
            counts[name] = int(row[0] or 0)
        return counts
    finally:
        conn.close()


def _user_entries(users_dir: Path, snap_root: Path) -> list[dict]:
    entries = []
    if not users_dir.is_dir():
        return entries
    out_users = snap_root / "users"
    out_users.mkdir(parents=True, exist_ok=True)
    for folder in sorted(users_dir.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        if folder.name in (".", "..") or "/" in folder.name:
            continue
        src_db = folder / "invest.db"
        dest_dir = out_users / folder.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        entry: dict = {"folder": folder.name, "tables": {}, "files": []}
        if src_db.is_file():
            dest_db = dest_dir / "invest.db"
            try:
                _snapshot_db(src_db, dest_db)
                st = src_db.stat()
                entry["db_bytes"] = int(dest_db.stat().st_size)
                entry["db_mtime"] = _iso(st.st_mtime)
                entry["tables"] = _table_counts(dest_db)
            except Exception as exc:
                entry["error"] = type(exc).__name__
        for path in sorted(folder.iterdir()):
            if path.is_symlink() or not path.is_file() or path.name in _SKIP_NAMES:
                continue
            if "/" in path.name or path.name in (".", ".."):
                continue
            target = dest_dir / path.name
            target.write_bytes(path.read_bytes())
            st = path.stat()
            entry["files"].append({
                "name": path.name,
                "bytes": int(st.st_size),
                "mtime": _iso(st.st_mtime),
            })
        entries.append(entry)
    return entries


def build_invest_backup(instance_path: Path, work_dir: Path) -> dict:
    """Write the zip under work_dir. Does not open live databases."""
    now = datetime.now(_TEHRAN)
    folder_name = now.strftime("invest-backup-%Y-%m-%d_%H%M")
    download_name = now.strftime("invest-backup-%Y-%m-%d.zip")
    snap = work_dir / folder_name
    snap.mkdir(parents=True, exist_ok=True)
    users = _user_entries(Path(instance_path) / "invest" / "users", snap)
    manifest = {
        "created_at": now.isoformat(timespec="seconds"),
        "user_count": len(users),
        "users": users,
    }
    (snap / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    zip_path = work_dir / download_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(snap.rglob("*")):
            if not path.is_file() or path.name.endswith(("-wal", "-shm")):
                continue
            archive.write(path, arcname=str(path.relative_to(work_dir)))
    digest = hashlib.sha256()
    with zip_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "zip_path": zip_path,
        "download_name": download_name,
        "users": len(users),
        "bytes": zip_path.stat().st_size,
        "sha256": digest.hexdigest(),
    }
