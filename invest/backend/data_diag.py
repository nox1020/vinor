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


_RO_HOLDS: dict[int, object] = {}


def _open_ro(path: Path) -> sqlite3.Connection:
    """Read a copy so the live file is never opened and no sidecar is created."""
    import tempfile

    hold = tempfile.TemporaryDirectory(prefix="vinor-ro-")
    dest = Path(hold.name) / "invest.db"
    dest.write_bytes(Path(path).read_bytes())
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.is_file():
            Path(str(dest) + suffix).write_bytes(side.read_bytes())
    conn = sqlite3.connect(dest)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    _RO_HOLDS[id(conn)] = hold
    return conn


def _close_ro(conn: sqlite3.Connection) -> None:
    hold = _RO_HOLDS.pop(id(conn), None)
    conn.close()
    if hold is not None:
        hold.cleanup()


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
        _close_ro(conn)
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


def invest_data_report(instance_path: Path, *, phone_last4: str = "", shapes: bool = False) -> dict:
    """Inventory only. Does not create directories or write SQLite."""
    root = Path(instance_path) / "invest"
    want = (phone_last4 or "").strip()
    users = []
    matched: list[Path] = []
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
            matched.append(folder)
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
    payload = {
        "ok": True,
        "invest_root_exists": root.is_dir(),
        "user_count": len(users),
        "users": users,
        "legacy": legacy,
        "root_backup_files": root_backups,
    }
    if shapes:
        payload["shapes"] = [_shape_user(folder, profiles) for folder in matched]
    return payload


_PERSIAN_DIGITS = re.compile(r"[\u06F0-\u06F9\u0660-\u0669]")
_SHAPE_TABLES = ("assets", "trades", "checks", "settings")
_JSON_ROUTES = (
    ("/invest/api/v1/dashboard", "dashboard"),
    ("/invest/api/v1/assets", "list_assets"),
    ("/invest/api/v1/trades/open", "trades_open"),
    ("/invest/api/v1/trades/closed", "trades_closed"),
    ("/invest/api/v1/settings", "get_settings"),
    ("/invest/api/v1/checks", "list_checks"),
    ("/invest/api/v1/checks/reminders", "check_reminders"),
    ("/invest/api/v1/quotes", "quotes"),
    ("/invest/api/v1/insights", "insights"),
)


class _FrozenMarket:
    """Cached market index only. Does not refresh or write the shared db."""

    def get_bundle(self, *, force: bool = False) -> dict:
        del force
        path = None
        try:
            from flask import current_app

            path = Path(current_app.instance_path) / "invest" / "market_index.db"
        except Exception:
            path = None
        if path is None or not path.is_file():
            return {
                "essentials": [],
                "wallex_markets": [],
                "inflation": None,
                "updated_at": None,
                "stale": True,
            }
        try:
            conn = _open_ro(path)
        except sqlite3.Error:
            return {
                "essentials": [],
                "wallex_markets": [],
                "inflation": None,
                "updated_at": None,
                "stale": True,
            }
        try:
            row = conn.execute(
                "SELECT payload, updated_at FROM market_latest WHERE id = 1"
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            _close_ro(conn)
        if not row:
            return {
                "essentials": [],
                "wallex_markets": [],
                "inflation": None,
                "updated_at": None,
                "stale": True,
            }
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["updated_at"] = row["updated_at"]
        payload["stale"] = True
        payload.setdefault("essentials", [])
        payload.setdefault("wallex_markets", [])
        return payload


class _Field:
    def __init__(self) -> None:
        self.types: dict[str, int] = {}
        self.nulls = 0
        self.str_min: int | None = None
        self.str_max: int | None = None
        self.persian = False
        self.saw_string = False

    def add_type(self, name: str) -> None:
        self.types[name] = self.types.get(name, 0) + 1

    def emit(self) -> dict:
        row: dict = {"types": self.types, "nulls": self.nulls}
        if self.saw_string:
            row["str_len"] = [self.str_min, self.str_max]
            row["persian_digits"] = self.persian
        return row


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def _note_string(field: _Field, text: str) -> None:
    field.saw_string = True
    size = len(text)
    field.str_min = size if field.str_min is None else min(field.str_min, size)
    field.str_max = size if field.str_max is None else max(field.str_max, size)
    if _PERSIAN_DIGITS.search(text):
        field.persian = True


def _walk_json(value: object, path: str, fields: dict[str, _Field]) -> None:
    field = fields.setdefault(path or "$", _Field())
    kind = _json_type(value)
    field.add_type(kind)
    if value is None:
        field.nulls += 1
        return
    if isinstance(value, str):
        _note_string(field, value)
        return
    if isinstance(value, list):
        for item in value:
            _walk_json(item, f"{path}[]", fields)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            shown = str(key) if _SAFE_KEY.fullmatch(str(key)) else "(nonstandard)"
            child = f"{path}.{shown}" if path else shown
            _walk_json(item, child, fields)


def _fields_of(body: object) -> dict:
    fields: dict[str, _Field] = {}
    if isinstance(body, dict):
        for key, item in body.items():
            shown = str(key) if _SAFE_KEY.fullmatch(str(key)) else "(nonstandard)"
            _walk_json(item, shown, fields)
    else:
        _walk_json(body, "$", fields)
    return {path: field.emit() for path, field in fields.items()}


def _stamp(path: Path) -> tuple | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _source_changed(before: dict[str, tuple | None], paths: list[Path]) -> bool:
    for path in paths:
        if _stamp(path) != before.get(str(path)):
            return True
    return False


def _table_fields(conn: sqlite3.Connection, table: str) -> dict:
    if not _SAFE_TABLE.fullmatch(table):
        return {}
    present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    if not present:
        return {}
    columns = []
    for row in conn.execute(f'PRAGMA table_info("{table}")'):
        name = str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        if _SAFE_KEY.fullmatch(name):
            columns.append(name)
    fields: dict[str, _Field] = {}
    if not columns:
        return {}
    quoted = ", ".join(f'"{name}"' for name in columns)
    for row in conn.execute(f'SELECT {quoted} FROM "{table}"'):
        for name in columns:
            value = row[name]
            field = fields.setdefault(name, _Field())
            if value is None:
                field.add_type("null")
                field.nulls += 1
                continue
            if isinstance(value, bool):
                field.add_type("bool")
            elif isinstance(value, int):
                field.add_type("int")
            elif isinstance(value, float):
                field.add_type("float")
            elif isinstance(value, bytes):
                field.add_type("blob")
                _note_string(field, "")
            else:
                field.add_type("string")
                _note_string(field, str(value))
    return {name: field.emit() for name, field in fields.items()}


def _copy_db(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    for suffix in ("-wal", "-shm"):
        side = Path(str(src) + suffix)
        if side.is_file():
            Path(str(dest) + suffix).write_bytes(side.read_bytes())


def _route_views() -> dict:
    from flask import Flask

    from invest.backend.routes.api import invest_api_bp

    probe = Flask("invest-shape-probe")
    probe.register_blueprint(invest_api_bp)
    return {
        endpoint: probe.view_functions[f"invest_api.{endpoint}"]
        for _, endpoint in _JSON_ROUTES
        if f"invest_api.{endpoint}" in probe.view_functions
    }


def _call_routes(phone: str) -> dict:
    from flask import current_app, session

    from invest.backend.context import close_request_context

    app = current_app._get_current_object()
    views = _route_views()
    out = {}
    for path, endpoint in _JSON_ROUTES:
        view = views.get(endpoint)
        if view is None:
            out[path] = {"status": None, "error": "missing", "fields": {}}
            continue
        status = None
        error = None
        fields: dict = {}
        try:
            with app.test_request_context(path, method="GET"):
                session["user_phone"] = phone
                session["user_id"] = phone
                try:
                    result = view()
                    if isinstance(result, tuple):
                        response, status = result[0], int(result[1])
                    else:
                        response = result
                        status = int(getattr(result, "status_code", 200))
                    body = response.get_json(silent=True)
                    fields = _fields_of(body)
                except Exception as exc:
                    error = type(exc).__name__
                finally:
                    close_request_context()
        except Exception as exc:
            error = type(exc).__name__
        out[path] = {"status": status, "error": error, "fields": fields}
    return out


def _shape_user(folder: Path, profiles: Path) -> dict:
    import tempfile

    from invest.backend.config import pop_diag, push_diag

    db = folder / "invest.db"
    profile = profiles / f"{folder.name}.json"
    watched = [db, profile, Path(str(db) + "-wal"), Path(str(db) + "-shm")]
    before = {str(path): _stamp(path) for path in watched}
    record = {
        "phone_last4": folder.name[-4:] if folder.name else "",
        "folder_len": len(folder.name),
        "source_changed": False,
        "tables": {},
        "routes": {},
    }
    if not db.is_file():
        record["routes_error"] = "missing"
        record["source_changed"] = _source_changed(before, watched)
        return record

    token = None
    try:
        with tempfile.TemporaryDirectory(prefix="vinor-invest-shape-") as tmp:
            copy = Path(tmp) / "invest.db"
            profile_copy = Path(tmp) / "profile.json"
            _copy_db(db, copy)
            try:
                conn = sqlite3.connect(copy)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only=ON")
                for table in _SHAPE_TABLES:
                    record["tables"][table] = _table_fields(conn, table)
            except sqlite3.Error as exc:
                record["tables_error"] = type(exc).__name__
            finally:
                conn.close()
            if profile.is_file():
                profile_copy.write_bytes(profile.read_bytes())
            else:
                profile_copy.write_text("{}", encoding="utf-8")
            token = push_diag({
                "phone": folder.name,
                "db": str(copy),
                "profile": str(profile_copy),
                "market": _FrozenMarket(),
            })
            record["routes"] = _call_routes(folder.name)
    except Exception as exc:
        record["routes_error"] = type(exc).__name__
    finally:
        if token is not None:
            pop_diag(token)
    record["source_changed"] = _source_changed(before, watched)
    return record
