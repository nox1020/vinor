# -*- coding: utf-8 -*-
"""Read-only inventory of Invest files. Never creates or rewrites them."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SAFE_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SAFE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DIGIT_RUN = re.compile(r"\d{8,}")
_COUNT_TABLES = (
    "assets",
    "trades",
    "checks",
    "capital_snapshots",
    "portfolio_snapshots",
    "settings",
    "schema_migrations",
)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_meta(path: Path) -> dict:
    try:
        st = path.stat()
    except OSError:
        return {"exists": False}
    return {"exists": True, "bytes": int(st.st_size), "mtime": _iso(st.st_mtime)}


def _mask_name(name: str) -> str:
    return _DIGIT_RUN.sub("*****", name)[:120]


def _shape(value: str) -> tuple[str, int | None]:
    text = value.lstrip()
    if not text:
        return "empty", 0
    if text[0] not in "[{":
        return "text", None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return "text", None
    if isinstance(parsed, list):
        return "list", len(parsed)
    if isinstance(parsed, dict):
        return "object", len(parsed)
    return "text", None


def _key_row(key: object, value: object) -> dict:
    raw_key = "" if key is None else str(key)
    raw_value = "" if value is None else str(value)
    shown = raw_key if _SAFE_KEY.fullmatch(raw_key) else "(nonstandard)"
    shape, items = _shape(raw_value)
    row = {"key": shown, "chars": len(raw_value), "shape": shape}
    if items is not None and shape in ("list", "object", "empty"):
        row["items"] = items
    return row


def _open_ro(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_summary(path: Path) -> dict:
    summary: dict = {"tables": [], "backup_tables": [], "counts": {}, "settings_keys": []}
    if not path.is_file():
        summary["error"] = "missing"
        return summary
    try:
        conn = _open_ro(path)
    except sqlite3.Error as exc:
        summary["error"] = type(exc).__name__
        return summary
    try:
        names = []
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            name = str(row["name"] or "")
            if _SAFE_TABLE.fullmatch(name):
                names.append(name)
        summary["tables"] = names
        summary["backup_tables"] = [name for name in names if "backup" in name.lower()]
        for name in names:
            if name in _COUNT_TABLES or name in summary["backup_tables"]:
                count = conn.execute(f'SELECT COUNT(*) AS n FROM "{name}"').fetchone()
                summary["counts"][name] = int(count["n"] or 0)
        if "trades" in names:
            for status in ("open", "closed"):
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM trades WHERE status = ?",
                    (status,),
                ).fetchone()
                summary["counts"][f"trades_{status}"] = int(row["n"] or 0)
        if "settings" in names:
            rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
            summary["settings_keys"] = [_key_row(row["key"], row["value"]) for row in rows]
        if "schema_migrations" in names:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            summary["schema_version"] = int(row["v"] or 0) if row and row["v"] is not None else 0
    except sqlite3.Error as exc:
        summary["error"] = type(exc).__name__
    finally:
        conn.close()
    return summary


def _sidecars(directory: Path, stem: str) -> list[dict]:
    found = []
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        interesting = (
            name.startswith(stem) and name != f"{stem}.db"
            or "backup" in name.lower()
            or name.endswith(".bak")
            or name.endswith(".vplusbak")
        )
        if not interesting:
            continue
        meta = _file_meta(path)
        meta["name"] = _mask_name(name)
        found.append(meta)
    return found


def _profile_summary(path: Path) -> dict:
    meta = _file_meta(path)
    if not meta.get("exists"):
        return meta
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta["keys"] = []
        meta["error"] = "unreadable"
        return meta
    if not isinstance(data, dict):
        meta["keys"] = []
        meta["shape"] = type(data).__name__
        return meta
    keys = []
    for key, value in data.items():
        if isinstance(value, str):
            encoded = value
        else:
            encoded = json.dumps(value, ensure_ascii=False, default=str)
        keys.append(_key_row(key, encoded))
    meta["keys"] = keys
    return meta


def _user_record(folder: Path, profiles: Path) -> dict:
    db = folder / "invest.db"
    record = {
        "phone_last4": folder.name[-4:] if folder.name else "",
        "folder_len": len(folder.name),
        "db": _file_meta(db),
        "sqlite": _sqlite_summary(db) if db.is_file() else {"tables": [], "counts": {}, "settings_keys": [], "backup_tables": []},
        "backup_files": _sidecars(folder, "invest"),
        "profile": _profile_summary(profiles / f"{folder.name}.json"),
    }
    return record


def _legacy(path: Path, label: str) -> dict:
    row = {"label": label, **_file_meta(path)}
    if path.is_file() and path.suffix == ".db":
        row["sqlite"] = _sqlite_summary(path)
        row["backup_files"] = _sidecars(path.parent, path.stem)
    return row


def invest_data_report(instance_path: Path, *, phone_last4: str = "") -> dict:
    """Inventory only. Does not create directories or write SQLite."""
    root = Path(instance_path) / "invest"
    want = (phone_last4 or "").strip()
    users = []
    users_dir = root / "users"
    profiles = root / "profiles"
    if users_dir.is_dir():
        for folder in sorted(users_dir.iterdir()):
            if not folder.is_dir():
                continue
            if "/" in folder.name or folder.name in (".", ".."):
                continue
            if want and not folder.name.endswith(want):
                continue
            users.append(_user_record(folder, profiles))
    repo_data = Path(__file__).resolve().parent.parent / "data" / "invest.db"
    legacy = [
        _legacy(Path(instance_path) / "invest.db", "instance/invest.db"),
        _legacy(root / "invest.db", "instance/invest/invest.db"),
        _legacy(Path(instance_path) / "data" / "invest.db", "instance/data/invest.db"),
        _legacy(repo_data, "invest/data/invest.db"),
        _legacy(root / "market_index.db", "instance/invest/market_index.db"),
    ]
    root_backups = _sidecars(root, "invest") if root.is_dir() else []
    return {
        "ok": True,
        "invest_root_exists": root.is_dir(),
        "user_count": len(users),
        "users": users,
        "legacy": legacy,
        "root_backup_files": root_backups,
    }
