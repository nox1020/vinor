# -*- coding: utf-8 -*-
"""PWO (برداشت ماهانه) — /invest/api/v1/pwo. ذخیره per-account در DB همان کاربر، مثل چک‌ها."""
from __future__ import annotations

import sqlite3

from flask import request

from invest_app.utils.dates import now_iso

from .auth import require_invest_auth
from .context import get_request_context
from .routes.api import _json_err, _json_ok, invest_api_bp

TARGET_KEY = "pwo_monthly_target"
DEFAULT_TARGET = 100_000_000.0
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class PwoError(Exception):
    def __init__(self, message: str, code: str = "validation", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _conn() -> sqlite3.Connection:
    return get_request_context().conn


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def parse_amount(raw, field: str = "amount") -> float:
    if isinstance(raw, bool):
        raise PwoError("مبلغ نامعتبر است.")
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        text = str(raw or "").translate(_DIGITS)
        for ch in (",", "٬", "،", " ", "_", "\u200c"):
            text = text.replace(ch, "")
        text = text.replace("٫", ".")
        try:
            val = float(text)
        except ValueError:
            raise PwoError("مبلغ نامعتبر است.") from None
    if val != val or val < 0 or val > 1e15:
        raise PwoError("مبلغ نامعتبر است.")
    return val


def _int(raw, lo: int, hi: int, label: str) -> int:
    try:
        val = int(str(raw).translate(_DIGITS).strip())
    except (TypeError, ValueError):
        raise PwoError(f"{label} نامعتبر است.") from None
    if not lo <= val <= hi:
        raise PwoError(f"{label} نامعتبر است.")
    return val


def _name(raw) -> str:
    name = " ".join(str(raw or "").split())
    if not name or len(name) > 60:
        raise PwoError("نام برداشت‌کننده نامعتبر است.")
    return name


def _get_target(conn) -> float:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (TARGET_KEY,)).fetchone()
    try:
        return float(row[0]) if row else DEFAULT_TARGET
    except (TypeError, ValueError):
        return DEFAULT_TARGET


def _withdrawer(conn, wid: int):
    row = conn.execute("SELECT * FROM pwo_withdrawers WHERE id=?", (wid,)).fetchone()
    if not row:
        raise PwoError("برداشت‌کننده پیدا نشد.", code="not_found", status=404)
    return row


def _w_public(r) -> dict:
    return {"id": r["id"], "name": r["name"], "sort_order": r["sort_order"],
            "archived": bool(r["archived"])}


def _e_public(r) -> dict:
    return {"id": r["id"], "withdrawer_id": r["withdrawer_id"], "year": r["year"],
            "month": r["month"], "amount": r["amount"], "note": r["note"],
            "updated_at": r["updated_at"]}


def snapshot(conn) -> dict:
    target = _get_target(conn)
    ws = [_w_public(r) for r in conn.execute(
        "SELECT * FROM pwo_withdrawers ORDER BY archived, sort_order, id")]
    es = [_e_public(r) for r in conn.execute(
        "SELECT * FROM pwo_entries ORDER BY year, month, withdrawer_id")]
    months: dict[tuple, dict] = {}
    years: dict[int, dict] = {}
    for e in es:
        m = months.setdefault((e["year"], e["month"]),
                              {"year": e["year"], "month": e["month"], "total": 0.0, "by_withdrawer": {}})
        m["total"] += e["amount"]
        m["by_withdrawer"][str(e["withdrawer_id"])] = e["amount"]
        y = years.setdefault(e["year"], {"year": e["year"], "total": 0.0, "by_withdrawer": {}})
        y["total"] += e["amount"]
        k = str(e["withdrawer_id"])
        y["by_withdrawer"][k] = y["by_withdrawer"].get(k, 0.0) + e["amount"]
    month_list = sorted(months.values(), key=lambda m: (m["year"], m["month"]))
    for m in month_list:
        m["met_target"] = m["total"] >= target
    return {"target": target, "withdrawers": ws, "entries": es,
            "totals": {"months": month_list, "years": sorted(years.values(), key=lambda y: y["year"])}}


def _upsert_entry(conn, wid: int, year: int, month: int, amount: float, note: str, *, overwrite=True) -> bool:
    ts = now_iso()
    if amount == 0:
        # صفر یعنی «برداشتی نیست»: ردیف صفر نگه نمی‌داریم (وگرنه حذف نفر به بایگانی می‌افتد).
        if not overwrite:
            return False
        conn.execute("DELETE FROM pwo_entries WHERE withdrawer_id=? AND year=? AND month=?",
                     (wid, year, month))
        return True
    if not overwrite:
        cur = conn.execute(
            "INSERT INTO pwo_entries (withdrawer_id, year, month, amount, note, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?) ON CONFLICT(withdrawer_id, year, month) DO NOTHING",
            (wid, year, month, amount, note, ts, ts))
        return cur.rowcount > 0
    # Atomic upsert (UNIQUE(withdrawer_id, year, month)); safe under concurrent saves.
    conn.execute(
        "INSERT INTO pwo_entries (withdrawer_id, year, month, amount, note, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?) ON CONFLICT(withdrawer_id, year, month)"
        " DO UPDATE SET amount=excluded.amount, note=excluded.note, updated_at=excluded.updated_at",
        (wid, year, month, amount, note, ts, ts))
    return True


def _ensure_unique_name(conn, name: str, exclude_id: int | None = None) -> None:
    row = conn.execute(
        "SELECT id FROM pwo_withdrawers WHERE archived=0 AND name=? AND id != ?",
        (name, exclude_id or 0)).fetchone()
    if row:
        raise PwoError("این نام تکراری است.", code="duplicate_name", status=409)


def _add_withdrawer(conn, name: str) -> int:
    ts = now_iso()
    order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM pwo_withdrawers").fetchone()[0]
    cur = conn.execute("INSERT INTO pwo_withdrawers (name, sort_order, archived, created_at, updated_at)"
                       " VALUES (?, ?, 0, ?, ?)", (name, order, ts, ts))
    return int(cur.lastrowid)


def _active_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM pwo_withdrawers WHERE archived=0").fetchone()[0]


def _run(fn):
    conn = _conn()
    try:
        result = fn(conn)
        conn.commit()
        return result if result is not None else _json_ok(pwo=snapshot(conn))
    except PwoError as exc:
        conn.rollback()
        return _json_err(exc.message, error=exc.code, status=exc.status)


def register_pwo_routes() -> None:
    @invest_api_bp.get("/pwo")
    @require_invest_auth
    def pwo_get():
        return _json_ok(pwo=snapshot(_conn()))

    @invest_api_bp.put("/pwo/target")
    @require_invest_auth
    def pwo_target():
        def _do(conn):
            val = parse_amount(_body().get("target"))
            if val <= 0:
                raise PwoError("هدف باید بیشتر از صفر باشد.")
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (TARGET_KEY, repr(val)))
        return _run(_do)

    @invest_api_bp.post("/pwo/withdrawers")
    @require_invest_auth
    def pwo_add_withdrawer():
        def _do(conn):
            name = _name(_body().get("name"))
            _ensure_unique_name(conn, name)
            _add_withdrawer(conn, name)
        return _run(_do)

    @invest_api_bp.route("/pwo/withdrawers/<int:wid>", methods=["PUT", "PATCH"])
    @require_invest_auth
    def pwo_update_withdrawer(wid: int):
        def _do(conn):
            row = _withdrawer(conn, wid)
            body = _body()
            name = _name(body["name"]) if "name" in body else row["name"]
            archived_in = bool(body["archived"]) if "archived" in body else bool(row["archived"])
            if not archived_in and (name != row["name"] or row["archived"]):
                _ensure_unique_name(conn, name, exclude_id=wid)
            order = _int(body["sort_order"], 0, 10_000, "ترتیب") if "sort_order" in body else row["sort_order"]
            archived = int(bool(body["archived"])) if "archived" in body else row["archived"]
            if archived and not row["archived"] and _active_count(conn) <= 1:
                raise PwoError("حداقل یک برداشت‌کننده لازم است.", code="last_withdrawer")
            conn.execute("UPDATE pwo_withdrawers SET name=?, sort_order=?, archived=?, updated_at=? WHERE id=?",
                         (name, order, archived, now_iso(), wid))
        return _run(_do)

    def _remove(wid: int):
        def _do(conn):
            row = _withdrawer(conn, wid)
            if not row["archived"] and _active_count(conn) <= 1:
                raise PwoError("حداقل یک برداشت‌کننده لازم است.", code="last_withdrawer")
            has = conn.execute("SELECT 1 FROM pwo_entries WHERE withdrawer_id=? LIMIT 1", (wid,)).fetchone()
            if has:  # برداشت‌های ثبت‌شده حفظ می‌شوند
                conn.execute("UPDATE pwo_withdrawers SET archived=1, updated_at=? WHERE id=?", (now_iso(), wid))
            else:
                conn.execute("DELETE FROM pwo_withdrawers WHERE id=?", (wid,))
        return _run(_do)

    @invest_api_bp.delete("/pwo/withdrawers/<int:wid>")
    @require_invest_auth
    def pwo_delete_withdrawer(wid: int):
        return _remove(wid)

    @invest_api_bp.post("/pwo/withdrawers/<int:wid>/delete")
    @require_invest_auth
    def pwo_delete_withdrawer_post(wid: int):
        return _remove(wid)

    @invest_api_bp.route("/pwo/entries", methods=["POST", "PUT"])
    @require_invest_auth
    def pwo_upsert_entry():
        def _do(conn):
            b = _body()
            wid = _int(b.get("withdrawer_id"), 1, 2**62, "برداشت‌کننده")
            _withdrawer(conn, wid)
            _upsert_entry(conn, wid, _int(b.get("year"), 1300, 1600, "سال"),
                          _int(b.get("month"), 1, 12, "ماه"), parse_amount(b.get("amount")),
                          str(b.get("note") or "")[:500])
        return _run(_do)

    @invest_api_bp.put("/pwo/months/<int:year>/<int:month>")
    @require_invest_auth
    def pwo_put_month(year: int, month: int):
        """ثبت یکجای یک ماه: {"amounts": {"<withdrawer_id>": amount, ...}}"""
        def _do(conn):
            y, m = _int(year, 1300, 1600, "سال"), _int(month, 1, 12, "ماه")
            amounts = _body().get("amounts")
            if not isinstance(amounts, dict) or not amounts:
                raise PwoError("مبالغ ماه نامعتبر است.")
            for k, v in amounts.items():
                wid = _int(k, 1, 2**62, "برداشت‌کننده")
                _withdrawer(conn, wid)
                _upsert_entry(conn, wid, y, m, parse_amount(v), "")
        return _run(_do)

    def _del_entry(eid: int):
        def _do(conn):
            if conn.execute("DELETE FROM pwo_entries WHERE id=?", (eid,)).rowcount == 0:
                raise PwoError("ردیف پیدا نشد.", code="not_found", status=404)
        return _run(_do)

    @invest_api_bp.delete("/pwo/entries/<int:eid>")
    @require_invest_auth
    def pwo_delete_entry(eid: int):
        return _del_entry(eid)

    @invest_api_bp.post("/pwo/entries/<int:eid>/delete")
    @require_invest_auth
    def pwo_delete_entry_post(eid: int):
        return _del_entry(eid)

    @invest_api_bp.post("/pwo/import")
    @require_invest_auth
    def pwo_import():
        """مهاجرت یک‌بارهٔ دادهٔ محلی. ردیف موجود سرور بازنویسی نمی‌شود مگر overwrite=true.
        {"target"?: n, "withdrawers": [{"name": "M", "archived"?: bool}], "overwrite"?: bool,
         "entries": [{"withdrawer": "M", "year": 1405, "month": 1, "amount": n}]}"""
        def _do(conn):
            b = _body()
            overwrite = bool(b.get("overwrite"))
            by_name: dict[str, int] = {}
            for r in conn.execute("SELECT id, name FROM pwo_withdrawers ORDER BY archived, id"):
                by_name.setdefault(r["name"], r["id"])  # active first, then oldest
            for w in b.get("withdrawers") or []:
                w = w if isinstance(w, dict) else {"name": w}
                name = _name(w.get("name"))
                if name not in by_name:
                    by_name[name] = _add_withdrawer(conn, name)
                    if w.get("archived"):
                        conn.execute("UPDATE pwo_withdrawers SET archived=1 WHERE id=?", (by_name[name],))
            if b.get("target") not in (None, ""):
                val = parse_amount(b["target"])
                if val > 0 and (overwrite or not conn.execute(
                        "SELECT 1 FROM settings WHERE key=? AND value NOT IN ('100000000','100000000.0')",
                        (TARGET_KEY,)).fetchone()):
                    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) "
                                 "DO UPDATE SET value=excluded.value", (TARGET_KEY, repr(val)))
            written = skipped = 0
            for e in b.get("entries") or []:
                if not isinstance(e, dict):
                    raise PwoError("ردیف نامعتبر است.")
                name = _name(e.get("withdrawer"))
                if name not in by_name:
                    by_name[name] = _add_withdrawer(conn, name)
                ok = _upsert_entry(conn, by_name[name], _int(e.get("year"), 1300, 1600, "سال"),
                                   _int(e.get("month"), 1, 12, "ماه"), parse_amount(e.get("amount")),
                                   str(e.get("note") or "")[:500], overwrite=overwrite)
                written, skipped = written + ok, skipped + (not ok)
            conn.commit()
            return _json_ok(written=written, skipped=skipped, pwo=snapshot(conn))
        return _run(_do)
