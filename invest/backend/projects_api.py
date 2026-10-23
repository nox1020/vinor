# -*- coding: utf-8 -*-
"""پروژه‌ها / پیمانکاری — /invest/api/v1/projects. per-account مثل ملک و دفتر.

هر ردیف همان ستون‌های شیت «پیمانکاری» است: تاریخ شروع، مبلغ قرارداد، تاریخ پایان،
هزینه، سود (= قرارداد − هزینه)، درصد سود (= سود ÷ مبلغ قرارداد) و توضیحات
(«کارفرما - نوع کار»). ردیفی که فقط توضیح دارد «در صف» (pipeline) است.

وضعیت مؤثر:
- finished: تمام‌شده؛ سودش «تحقق‌یافته» است.
- active: در جریان؛ سودش «پیش‌بینی» است و جزو سود تحقق‌یافته نیست.
- pipeline: هنوز مبلغ ندارد.
status_mode = auto یعنی از روی داده‌ها تعیین می‌شود (پایانِ گذشته ⇒ تمام‌شده).
بایگانی چیزی را پاک نمی‌کند؛ ردیف بایگانی‌شده فقط از جمع‌ها بیرون می‌رود.
"""
from __future__ import annotations

import jdatetime

from invest_app.utils.dates import now_iso

from .auth import require_invest_auth
from .biz_api import _jd, parse_jdate
from .pwo_api import PwoError as ProjectError
from .pwo_api import _body, _conn, idempotent, parse_amount, remember_key
from .routes.api import _json_err, _json_ok, invest_api_bp

STATUS_AUTO = "auto"
STATUSES = ("pipeline", "active", "finished")
MODES = (STATUS_AUTO, *STATUSES)
_FIELDS = ("title", "work_type", "start_date", "end_date", "contract_amount", "cost",
           "status_mode", "note")


def split_description(raw) -> tuple[str, str]:
    """«بهادری - دیوارکشی» → ("بهادری", "دیوارکشی")."""
    text = " ".join(str(raw or "").split())
    for sep in (" - ", " – ", " — ", "-", "–"):
        if sep in text:
            a, b = text.split(sep, 1)
            return a.strip()[:200], b.strip()[:200]
    return text[:200], ""


def effective_status(row, today: jdatetime.date | None = None) -> str:
    mode = str(row["status_mode"] or STATUS_AUTO)
    if mode in STATUSES:
        return mode
    contract, cost = float(row["contract_amount"] or 0), float(row["cost"] or 0)
    if contract <= 0 and cost <= 0 and not row["start_date"]:
        return "pipeline"
    end = str(row["end_date"] or "")
    today = today or jdatetime.date.today()
    if end and _jd(end) <= today:
        return "finished"
    if contract <= 0 and cost <= 0:
        return "pipeline"
    return "active"


def project_public(r, today=None) -> dict:
    contract, cost = float(r["contract_amount"] or 0), float(r["cost"] or 0)
    status = effective_status(r, today)
    profit = contract - cost if contract > 0 else None
    days = None
    if r["start_date"] and r["end_date"]:
        days = (_jd(r["end_date"]) - _jd(r["start_date"])).days
    desc = r["title"] + (f" - {r['work_type']}" if r["work_type"] else "")
    return {
        "id": r["id"], "title": r["title"], "work_type": r["work_type"], "description": desc,
        "start_date": r["start_date"], "end_date": r["end_date"],
        "contract_amount": contract, "cost": cost, "profit": profit,
        # مثل شیت: درصد سود = سود ÷ مبلغ قرارداد
        "profit_pct": (profit / contract * 100.0) if profit is not None else None,
        "status": status, "status_mode": r["status_mode"] or STATUS_AUTO,
        "note": r["note"], "days": days,
        "archived": bool(r["archived_at"]), "archived_at": r["archived_at"],
        "updated_at": r["updated_at"],
    }


def snapshot(conn) -> dict:
    today = jdatetime.date.today()
    items = [project_public(r, today) for r in conn.execute(
        "SELECT * FROM biz_projects ORDER BY CASE WHEN start_date = '' THEN 1 ELSE 0 END,"
        " start_date, id")]
    live = [p for p in items if not p["archived"]]

    def total(status, key):
        return sum((p[key] or 0) for p in live if p["status"] == status)

    counts = {s: sum(1 for p in live if p["status"] == s) for s in STATUSES}
    realized, expected = total("finished", "profit"), total("active", "profit")
    return {
        "items": items,
        "totals": {
            "count": len(live), "archived_count": len(items) - len(live), **{f"{s}_count": n for s, n in counts.items()},
            "realized_profit": realized, "expected_profit": expected,
            "sheet_profit": realized + expected,
            "finished_contract": total("finished", "contract_amount"),
            "finished_cost": total("finished", "cost"),
            "active_contract": total("active", "contract_amount"),
            "active_cost": total("active", "cost"),
        },
    }


def _fields(b: dict, row=None) -> dict:
    def pick(k, fn, default):
        return fn(b[k]) if k in b else (row[k] if row is not None else default)

    if "description" in b and "title" not in b:
        t, w = split_description(b.get("description"))
        b = {**b, "title": t, **({"work_type": w} if "work_type" not in b else {})}
    title = pick("title", lambda v: " ".join(str(v or "").split())[:200], "")
    if not title:
        raise ProjectError("نام کارفرما یا عنوان پروژه لازم است.")
    work = pick("work_type", lambda v: " ".join(str(v or "").split())[:200], "")
    start = pick("start_date", lambda v: parse_jdate(v, required=False), "")
    end = pick("end_date", lambda v: parse_jdate(v, required=False), "")
    if start and end and _jd(end) < _jd(start):
        raise ProjectError("تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد.")
    amt = lambda v: parse_amount(v) if v not in (None, "") else 0.0  # noqa: E731
    contract = pick("contract_amount", amt, 0.0)
    cost = pick("cost", amt, 0.0)
    mode = pick("status_mode", lambda v: str(v or STATUS_AUTO).strip() or STATUS_AUTO, STATUS_AUTO)
    if "status" in b and "status_mode" not in b:
        mode = str(b["status"] or STATUS_AUTO).strip() or STATUS_AUTO
    if mode not in MODES:
        raise ProjectError("وضعیت پروژه نامعتبر است.")
    if mode in ("active", "finished") and contract <= 0:
        raise ProjectError("برای پروژهٔ در جریان یا تمام‌شده، مبلغ قرارداد لازم است.")
    note = pick("note", lambda v: str(v or "")[:500], "")
    return {"title": title, "work_type": work, "start_date": start, "end_date": end,
            "contract_amount": contract, "cost": cost, "status_mode": mode, "note": note}


def _archived_at(b: dict, row) -> str | None:
    prev = row["archived_at"] if row is not None else None
    if "archived" not in b:
        return prev
    flag = b["archived"]
    if isinstance(flag, str):
        flag = flag.strip().lower() in ("1", "true", "yes")
    return (prev or now_iso()) if flag else None


def _insert(conn, f: dict, archived_at=None) -> None:
    ts = now_iso()
    conn.execute(
        "INSERT INTO biz_projects (title, work_type, start_date, end_date, contract_amount, cost,"
        " status_mode, note, archived_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (*(f[k] for k in _FIELDS), archived_at, ts, ts))


def _row(conn, pid: int):
    row = conn.execute("SELECT * FROM biz_projects WHERE id=?", (pid,)).fetchone()
    if not row:
        raise ProjectError("پروژه پیدا نشد.", code="not_found", status=404)
    return row


def _run(fn):
    conn = _conn()

    def ok(key):
        try:
            result = fn(conn)
            remember_key(conn, key)
            conn.commit()
            return result if result is not None else _json_ok(projects=snapshot(conn))
        except ProjectError as exc:
            conn.rollback()
            return _json_err(exc.message, error=exc.code, status=exc.status)

    return idempotent(conn, ok, lambda: _json_ok(projects=snapshot(conn), replayed=True))


def _dedupe_key(f: dict) -> tuple:
    return (f["title"], f["work_type"], f["start_date"], round(f["contract_amount"]), round(f["cost"]))


def register_project_routes() -> None:
    @invest_api_bp.get("/projects")
    @require_invest_auth
    def projects_get():
        return _run(lambda conn: None)

    @invest_api_bp.post("/projects")
    @require_invest_auth
    def projects_add():
        def _do(conn):
            b = _body()
            _insert(conn, _fields(b), _archived_at(b, None))
        return _run(_do)

    @invest_api_bp.route("/projects/<int:pid>", methods=["PUT", "PATCH"])
    @require_invest_auth
    def projects_update(pid: int):
        def _do(conn):
            row = _row(conn, pid)
            b = _body()
            f = _fields(b, row)
            conn.execute(
                "UPDATE biz_projects SET title=?, work_type=?, start_date=?, end_date=?,"
                " contract_amount=?, cost=?, status_mode=?, note=?, archived_at=?, updated_at=?"
                " WHERE id=?",
                (*(f[k] for k in _FIELDS), _archived_at(b, row), now_iso(), pid))
        return _run(_do)

    def _delete(pid: int):
        def _do(conn):
            _row(conn, pid)
            conn.execute("DELETE FROM biz_projects WHERE id=?", (pid,))
        return _run(_do)

    @invest_api_bp.delete("/projects/<int:pid>")
    @require_invest_auth
    def projects_delete(pid: int):
        return _delete(pid)

    @invest_api_bp.post("/projects/<int:pid>/delete")
    @require_invest_auth
    def projects_delete_post(pid: int):
        return _delete(pid)

    @invest_api_bp.get("/projects/export")
    @require_invest_auth
    def projects_export():
        conn = _conn()
        rows = [{**{k: r[k] for k in _FIELDS}, "archived": bool(r["archived_at"])}
                for r in conn.execute("SELECT * FROM biz_projects ORDER BY id")]
        return _json_ok(export={"projects": rows})

    @invest_api_bp.post("/projects/import")
    @require_invest_auth
    def projects_import():
        """ورود از شیت. فقط اضافه می‌کند: ردیفی که عیناً موجود است دوباره نوشته نمی‌شود و
        هیچ ردیف موجودی تغییر نمی‌کند. {"projects": [{...}]}"""
        def _do(conn):
            rows = _body().get("projects")
            if not isinstance(rows, list):
                raise ProjectError("فهرست projects لازم است.")
            seen = {_dedupe_key(_fields({}, r)) for r in conn.execute("SELECT * FROM biz_projects")}
            written = skipped = 0
            for i, raw in enumerate(rows, 1):
                if not isinstance(raw, dict):
                    raise ProjectError(f"ردیف {i} نامعتبر است.")
                try:
                    f = _fields(dict(raw))
                except ProjectError as exc:
                    raise ProjectError(f"ردیف {i}: {exc.message}") from None
                k = _dedupe_key(f)
                if k in seen:
                    skipped += 1
                    continue
                seen.add(k)
                _insert(conn, f, now_iso() if raw.get("archived") else None)
                written += 1
            return _json_ok(written=written, skipped=skipped, projects=snapshot(conn))
        return _run(_do)
