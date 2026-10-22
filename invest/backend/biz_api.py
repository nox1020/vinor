# -*- coding: utf-8 -*-
"""کسب‌وکار ملک — /invest/api/v1/biz. per-account مثل چک‌ها و PWO.

- سابقه خرید و فروش ملک (biz_property_trades)
- جدول ماهانه: کارمندان، تبلیغات، درآمد (biz_monthly_ops). ستون PWO از ماژول PWO خوانده می‌شود
  (تکرار نمی‌شود). خالص ماه = درآمد − کارمندان − PWO − تبلیغات.
"""
from __future__ import annotations

import re

import jdatetime

from invest_app.utils.dates import now_iso

from .auth import require_invest_auth
from .pwo_api import PwoError as BizError
from .pwo_api import _body, _conn, _int, parse_amount
from .pwo_api import snapshot as pwo_snapshot
from .routes.api import _json_err, _json_ok, invest_api_bp

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE_RE = re.compile(r"^\s*(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})\s*$")


def parse_jdate(raw, *, required: bool = True) -> str:
    """'1405/01/20' یا '20/01/1405' → '1405/01/20'. خالی فقط وقتی required=False."""
    text = str(raw or "").translate(_DIGITS).strip()
    if not text:
        if required:
            raise BizError("تاریخ لازم است.")
        return ""
    m = _DATE_RE.match(text)
    if not m:
        raise BizError("تاریخ نامعتبر است.")
    a, b, c = (int(x) for x in m.groups())
    y, mo, d = (a, b, c) if a > 31 else (c, b, a)
    try:
        jdatetime.date(y, mo, d)
    except ValueError:
        raise BizError("تاریخ نامعتبر است.") from None
    if not 1300 <= y <= 1600:
        raise BizError("تاریخ نامعتبر است.")
    return f"{y:04d}/{mo:02d}/{d:02d}"


def _jd(s: str):
    y, m, d = (int(x) for x in s.split("/"))
    return jdatetime.date(y, m, d)


def trade_public(r) -> dict:
    buy, sell = float(r["buy_amount"]), float(r["sell_amount"])
    sold = bool(r["sell_date"]) and sell > 0
    profit = sell - buy if sold else None
    days = (_jd(r["sell_date"]) - _jd(r["buy_date"])).days if r["sell_date"] else None
    return {
        "id": r["id"], "buy_date": r["buy_date"], "sell_date": r["sell_date"],
        "buy_amount": buy, "sell_amount": sell, "area": r["area"], "title": r["title"],
        "extra_cost": float(r["extra_cost"]), "note": r["note"],
        "days": days, "profit": profit,
        # مثل شیت: درصد سود/زیان = سود ÷ مبلغ فروش
        "profit_pct": (profit / sell * 100.0) if profit is not None and sell > 0 else None,
        "updated_at": r["updated_at"],
    }


def _month_public(year: int, month: int, op, pwo: float) -> dict:
    staff = float(op["staff"]) if op else 0.0
    ads = float(op["ads"]) if op else 0.0
    income = float(op["income"]) if op else 0.0
    return {"year": year, "month": month, "id": op["id"] if op else None,
            "staff": staff, "pwo": pwo, "ads": ads, "income": income,
            "note": op["note"] if op else "",
            "net": income - staff - pwo - ads, "has_ops": op is not None}


def snapshot(conn, year: int | None = None) -> dict:
    trades = [trade_public(r) for r in conn.execute(
        "SELECT * FROM biz_property_trades ORDER BY buy_date, id")]
    pwo_months = {(m["year"], m["month"]): m["total"]
                  for m in pwo_snapshot(conn)["totals"]["months"]}
    ops = {(r["year"], r["month"]): r for r in conn.execute("SELECT * FROM biz_monthly_ops")}
    years = sorted({y for y, _ in ops} | {y for y, _ in pwo_months})
    if year is None:
        year = jdatetime.date.today().year
    if year not in years:
        years.append(year)
        years.sort()
    months = [_month_public(year, m, ops.get((year, m)), float(pwo_months.get((year, m), 0.0)))
              for m in range(1, 13)]
    tot = {k: sum(m[k] for m in months) for k in ("staff", "pwo", "ads", "income", "net")}
    sold = [t for t in trades if t["profit"] is not None]
    return {
        "trades": trades,
        "trades_totals": {"count": len(trades), "profit": sum(t["profit"] for t in sold),
                          "buy": sum(t["buy_amount"] for t in trades),
                          "sell": sum(t["sell_amount"] for t in sold),
                          "extra_cost": sum(t["extra_cost"] for t in trades)},
        "year": year, "years": years, "months": months, "months_totals": tot,
    }


def _trade_fields(b: dict, row=None) -> tuple:
    def pick(k, fn, default):
        return fn(b[k]) if k in b else (row[k] if row is not None else default)
    buy_date = pick("buy_date", parse_jdate, None)
    if buy_date is None:
        raise BizError("تاریخ خرید لازم است.")
    sell_date = pick("sell_date", lambda v: parse_jdate(v, required=False), "")
    buy = pick("buy_amount", parse_amount, None)
    if buy is None or buy <= 0:
        raise BizError("مبلغ خرید باید بیشتر از صفر باشد.")
    sell = pick("sell_amount", lambda v: parse_amount(v) if v not in (None, "") else 0.0, 0.0)
    if sell > 0 and not sell_date:
        raise BizError("برای مبلغ فروش، تاریخ فروش لازم است.")
    if sell_date and sell <= 0:
        raise BizError("برای تاریخ فروش، مبلغ فروش لازم است.")
    if sell_date and _jd(sell_date) < _jd(buy_date):
        raise BizError("تاریخ فروش نمی‌تواند قبل از تاریخ خرید باشد.")
    area = pick("area", lambda v: parse_amount(v) if v not in (None, "") else None, None)
    title = pick("title", lambda v: " ".join(str(v or "").split())[:200], "")
    extra = pick("extra_cost", lambda v: parse_amount(v) if v not in (None, "") else 0.0, 0.0)
    note = pick("note", lambda v: str(v or "")[:500], "")
    return buy_date, sell_date, buy, sell, area, title, extra, note


def _insert_trade(conn, f: tuple) -> None:
    ts = now_iso()
    conn.execute("INSERT INTO biz_property_trades (buy_date, sell_date, buy_amount, sell_amount, area,"
                 " title, extra_cost, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (*f, ts, ts))


def _upsert_month(conn, y: int, m: int, b: dict) -> None:
    row = conn.execute("SELECT * FROM biz_monthly_ops WHERE year=? AND month=?", (y, m)).fetchone()
    vals = {}
    for k in ("staff", "ads", "income"):
        if k in b:
            vals[k] = parse_amount(b[k]) if b[k] not in (None, "") else 0.0
        else:
            vals[k] = float(row[k]) if row else 0.0
    note = str(b.get("note") or "")[:500] if "note" in b else (row["note"] if row else "")
    ts = now_iso()
    conn.execute(
        "INSERT INTO biz_monthly_ops (year, month, staff, ads, income, note, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(year, month) DO UPDATE SET staff=excluded.staff,"
        " ads=excluded.ads, income=excluded.income, note=excluded.note, updated_at=excluded.updated_at",
        (y, m, vals["staff"], vals["ads"], vals["income"], note, ts, ts))


def _year_arg() -> int | None:
    from flask import request
    raw = request.args.get("year")
    return _int(raw, 1300, 1600, "سال") if raw not in (None, "") else None


def _run(fn, year=None):
    conn = _conn()
    try:
        result = fn(conn)
        conn.commit()
        return result if result is not None else _json_ok(biz=snapshot(conn, year))
    except BizError as exc:
        conn.rollback()
        return _json_err(exc.message, error=exc.code, status=exc.status)


def _trade_row(conn, tid: int):
    row = conn.execute("SELECT * FROM biz_property_trades WHERE id=?", (tid,)).fetchone()
    if not row:
        raise BizError("معامله پیدا نشد.", code="not_found", status=404)
    return row


def register_biz_routes() -> None:
    @invest_api_bp.get("/biz")
    @require_invest_auth
    def biz_get():
        return _run(lambda conn: None, _year_arg())

    @invest_api_bp.post("/biz/trades")
    @require_invest_auth
    def biz_add_trade():
        return _run(lambda conn: _insert_trade(conn, _trade_fields(_body())), _year_arg())

    @invest_api_bp.route("/biz/trades/<int:tid>", methods=["PUT", "PATCH"])
    @require_invest_auth
    def biz_update_trade(tid: int):
        def _do(conn):
            f = _trade_fields(_body(), _trade_row(conn, tid))
            conn.execute("UPDATE biz_property_trades SET buy_date=?, sell_date=?, buy_amount=?,"
                         " sell_amount=?, area=?, title=?, extra_cost=?, note=?, updated_at=? WHERE id=?",
                         (*f, now_iso(), tid))
        return _run(_do, _year_arg())

    def _del_trade(tid: int):
        def _do(conn):
            _trade_row(conn, tid)
            conn.execute("DELETE FROM biz_property_trades WHERE id=?", (tid,))
        return _run(_do, _year_arg())

    @invest_api_bp.delete("/biz/trades/<int:tid>")
    @require_invest_auth
    def biz_delete_trade(tid: int):
        return _del_trade(tid)

    @invest_api_bp.post("/biz/trades/<int:tid>/delete")
    @require_invest_auth
    def biz_delete_trade_post(tid: int):
        return _del_trade(tid)

    @invest_api_bp.put("/biz/months/<int:year>/<int:month>")
    @require_invest_auth
    def biz_put_month(year: int, month: int):
        """{"staff"?, "ads"?, "income"?, "note"?} — PWO اینجا ثبت نمی‌شود (ماژول PWO)."""
        y, m = year, month

        def _do(conn):
            _int(y, 1300, 1600, "سال")
            _int(m, 1, 12, "ماه")
            _upsert_month(conn, y, m, _body())
        return _run(_do, year)

    def _del_month(year: int, month: int):
        def _do(conn):
            if conn.execute("DELETE FROM biz_monthly_ops WHERE year=? AND month=?",
                            (year, month)).rowcount == 0:
                raise BizError("ردیف پیدا نشد.", code="not_found", status=404)
        return _run(_do, year)

    @invest_api_bp.delete("/biz/months/<int:year>/<int:month>")
    @require_invest_auth
    def biz_delete_month(year: int, month: int):
        return _del_month(year, month)

    @invest_api_bp.post("/biz/months/<int:year>/<int:month>/delete")
    @require_invest_auth
    def biz_delete_month_post(year: int, month: int):
        return _del_month(year, month)

    @invest_api_bp.post("/biz/import")
    @require_invest_auth
    def biz_import():
        """ورود یک‌باره. بازنویسی هرگز: اگر حساب معامله یا ردیف ماهانه دارد، هیچ چیز نوشته نمی‌شود.
        {"trades": [{...}], "months": [{"year", "month", "staff", "ads", "income"}]}"""
        def _do(conn):
            b = _body()
            if conn.execute("SELECT 1 FROM biz_property_trades UNION ALL "
                            "SELECT 1 FROM biz_monthly_ops LIMIT 1").fetchone():
                return _json_ok(written=0, already_has_data=True, biz=snapshot(conn))
            n = 0
            for t in b.get("trades") or []:
                if not isinstance(t, dict):
                    raise BizError("ردیف نامعتبر است.")
                _insert_trade(conn, _trade_fields(t))
                n += 1
            for mo in b.get("months") or []:
                if not isinstance(mo, dict):
                    raise BizError("ردیف نامعتبر است.")
                y = _int(mo.get("year"), 1300, 1600, "سال")
                _upsert_month(conn, y, _int(mo.get("month"), 1, 12, "ماه"),
                              {k: mo[k] for k in ("staff", "ads", "income", "note") if k in mo})
                n += 1
            conn.commit()
            return _json_ok(written=n, biz=snapshot(conn))
        return _run(_do)
