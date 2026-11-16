import io
import json
import os
import sys
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, Flask, flash, get_flashed_messages, make_response, redirect, render_template_string, request, session, url_for

from .curds import CreateDB, curdCommands, natural_flow_range_minutes_from_manage_row
from .dapi import api as DivarApi, pack_login_cookie
from .loadConfig import configBot
from .paths import config_file, data_path, is_configured, load_config, load_file_config

# Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# [vinor] پنل وب ربات به‌صورت Blueprint زیر /probot روی خود وینور سوار می‌شود.
# مقداردهی دیتابیس تنبل است (اولین درخواست) تا import این ماژول در وینور هیچ اثری نداشته باشد
# و وقتی ربات تنظیم نشده، وینور سالم بماند. این پنل هیچ scheduler یا polling اجرا نمی‌کند؛
# فرمان‌ها در جدول web_commands صف می‌شوند و worker پروسهٔ ربات اجرایشان می‌کند.
URL_PREFIX = "/probot"
bp = Blueprint("probot", __name__, url_prefix=URL_PREFIX)

Datas = None
db = None
curd = None
divar_api = None
DEFAULT_ADMIN_ID = 0
_INIT_DONE = False

# کلیدهای session پنل با پیشوند probot_ تا با session وینور تداخل نکنند.
_SESSION_KEYS = ("probot_web_auth", "probot_panel_chatid", "probot_otp_phone", "probot_open_otp_modal")
_RELAY_ENDPOINTS = {"probot.divar_relay", "probot.divar_relay_health"}


def _ensure_init():
    global Datas, db, curd, divar_api, DEFAULT_ADMIN_ID, _INIT_DONE
    if _INIT_DONE:
        return
    Datas = configBot()
    db = CreateDB(Datas)
    db.create()
    curd = curdCommands(Datas)
    curd.cTable_manage()
    curd.cTable_adminp()
    curd.cTable_logins()
    curd.cTable_sents()
    curd.cTable_admins()
    curd.cTable_jobs()
    curd.cTable_tokens()
    curd.cTable_web_commands()
    curd.cTable_web_panel_auth()
    DEFAULT_ADMIN_ID = int(Datas.admin) if Datas.admin is not None else 0
    divar_api = DivarApi()
    _INIT_DONE = True


def _clear_probot_session():
    for k in _SESSION_KEYS:
        session.pop(k, None)


_DISABLED_HTML = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ربات غیرفعال است</title></head>
<body style="font-family:Tahoma,sans-serif;background:#020617;color:#e5e7eb;padding:24px">
<h2>🤖 پنل ربات هنوز فعال نشده است</h2>
<p>توکن ربات بله و شناسهٔ ادمین تنظیم نشده‌اند. راهنما: probot/README.md</p></body></html>"""


@bp.before_request
def _probot_before_request():
    if request.endpoint in _RELAY_ENDPOINTS:
        return None
    if not is_configured():
        resp = make_response(_DISABLED_HTML, 503)
        resp.headers["Cache-Control"] = "no-store"
        return resp
    _ensure_init()
    return None


@bp.after_request
def _probot_no_index(resp):
    resp.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _csrf_field():
    try:
        from flask_wtf.csrf import generate_csrf

        return '<input type="hidden" name="csrf_token" value="%s">' % generate_csrf()
    except Exception:
        return ""


@bp.context_processor
def _probot_template_ctx():
    return {"probot_prefix": URL_PREFIX, "probot_csrf_field": _csrf_field}


# for passenger_wsgi compatibility (پنل هیچ scheduler ندارد)
scheduler = None


def restore_jobs():
    return


def _load_raw_config():
    """فقط محتوای configs.json (بدون env) — چون همین dict دوباره در فایل نوشته می‌شود."""
    return load_file_config()


def _save_raw_config(config):
    path = config_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_bale_status():
    try:
        with open(data_path("bale_status.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"state": "unknown", "detail": "بله غیرفعال یا هنوز ثبت نشده", "updated_at": "-"}


def _load_web_message_logs(limit=30, panel_chatid=None):
    try:
        with open(data_path("web_message_logs.json"), "r", encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            return []
        rows = rows[-800:][::-1]
        cleaned = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if panel_chatid is not None:
                try:
                    cid = r.get("chat_id")
                    if cid is None or int(cid) != int(panel_chatid):
                        continue
                except (TypeError, ValueError):
                    continue
            raw_text = str(r.get("text", "")).replace("\x00", "").strip()
            cleaned.append(
                {
                    "ts": str(r.get("ts", "-")).replace("\x00", "") or "-",
                    "text": raw_text or "-",
                }
            )
            if len(cleaned) >= limit:
                break
        return cleaned
    except Exception:
        return []


def _panel_chatid() -> int:
    """شناسهٔ چت ادمین جاری در پنل (همان chatid ربات بله)."""
    try:
        return int(session.get("probot_panel_chatid", 0) or 0)
    except (TypeError, ValueError):
        return 0


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("probot_web_auth") or _panel_chatid() <= 0:
            return redirect(url_for(".login"), code=303)
        return fn(*args, **kwargs)

    return wrapper


def _enqueue_command(command_type, payload=None):
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    return curd.addWebCommand(chatid=_panel_chatid(), command_type=command_type, payload_json=payload_json)


def _normalize_phone(raw_phone: str):
    """
    نرمال‌سازی شماره موبایل:
    - تبدیل ارقام فارسی/عربی به انگلیسی
    - حذف فاصله/خط فاصله
    - تبدیل +98/98 به 0
    """
    if raw_phone is None:
        return ""
    text = str(raw_phone).strip()
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    text = text.translate(trans)
    text = text.replace(" ", "").replace("-", "")
    if text.startswith("+98"):
        text = "0" + text[3:]
    elif text.startswith("98") and len(text) >= 12:
        text = "0" + text[2:]
    # شماره در DB گاهی به صورت ۹۱۲… (۱۰ رقم، بدون ۰ ابتدایی) ذخیره شده
    elif len(text) == 10 and text.startswith("9") and text.isdigit():
        text = "0" + text
    return text


def _admin_rows_for_panel():
    """ادمین پیش‌فرض از configs اول، بقیه از جدول admins."""
    primary = int(Datas.admin) if Datas.admin is not None else None
    db_ids = set()
    for a in curd.getAdmins() or []:
        try:
            db_ids.add(int(a))
        except (TypeError, ValueError):
            pass
    rows = []
    if primary is not None:
        rows.append({"id": primary, "is_primary": True})
    for aid in sorted(db_ids):
        if primary is not None and aid == primary:
            continue
        rows.append({"id": aid, "is_primary": False})
    return rows


def _get_nardeban_runtime_status():
    """
    وضعیت اجرای نردبان از دید پنل:
    - job فعال ثبت‌شده در جدول jobs
    - فرمان‌های start/stop در صف که هنوز پردازش نشده‌اند
    """
    cid = _panel_chatid()
    job_id = curd.getJob(chatid=cid)
    active_jobs_count = 1 if job_id else 0

    pending_start = 0
    pending_stop = 0
    for row in curd.getPendingWebCommands(limit=100):
        try:
            row_chat = int(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if row_chat != cid:
            continue
        command_type = row[2]
        if command_type == "startJob":
            pending_start += 1
        elif command_type == "remJob":
            pending_stop += 1

    start_command_in_flight = curd.has_web_command_in_flight(cid, "startJob")

    state_text = "فعال" if active_jobs_count > 0 else "متوقف"
    if pending_stop > 0:
        state_text = "درحال توقف..."
    elif pending_start > 0:
        state_text = "درحال شروع..."

    return {
        "job_id": job_id or "-",
        "active_jobs_count": active_jobs_count,
        "pending_start": pending_start,
        "pending_stop": pending_stop,
        "start_command_in_flight": start_command_in_flight,
        "state_text": state_text,
    }


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = _normalize_phone(request.form.get("phone", ""))
        password = (request.form.get("password") or "").strip()
        if not phone:
            flash("شماره موبایل را وارد کنید.", "err")
        elif not password:
            flash("رمز پنل را وارد کنید.", "err")
        else:
            chatid = curd.find_chatid_by_login_phone(phone)
            if not chatid:
                flash("این شماره در لیست لاگین‌های دیوار ثبت نشده است؛ ابتدا از ربات بله همان شماره را اضافه کنید.", "err")
            elif not curd.verify_web_panel_password(chatid, password):
                flash(
                    "رمز اشتباه است یا هنوز رمز دریافت نکرده‌اید. پس از اولین «لاگین جدید» موفق در ربات، رمز پنل برایتان ارسال می‌شود.",
                    "err",
                )
            else:
                curd.addManage(chatid)
                _clear_probot_session()
                session["probot_web_auth"] = True
                session["probot_panel_chatid"] = int(chatid)
                flash("ورود موفق بود؛ پنل با همان حساب ربات بله شما همگام است.", "ok")
                return redirect(url_for(".panel"), code=303)

    html = """
    <!doctype html>
    <html lang="fa" dir="rtl">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
      <title>ورود پنل وب</title>
      <style>
        :root { color-scheme: dark; }
        *, *::before, *::after { box-sizing: border-box; }
        html { -webkit-text-size-adjust: 100%; }
        html, body { background:#020617 !important; color:#e5e7eb !important; }
        body { font-family: Tahoma, sans-serif; margin:0; padding:max(12px, env(safe-area-inset-top)) max(12px, env(safe-area-inset-right)) max(12px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left)); }
        .box { max-width: 420px; width:100%; margin: min(48px, 12vh) auto; background:#0f172a !important; border:1px solid #334155; border-radius:16px; padding:clamp(16px, 4vw, 22px); }
        h2 { margin: 0 0 14px 0; }
        .muted { color:#94a3b8; font-size:13px; margin-bottom:12px; line-height:1.55; }
        input,button { width:100%; box-sizing:border-box; padding:12px 14px; min-height:44px; border-radius:10px; border:1px solid #334155; background:#020617 !important; color:#e5e7eb !important; }
        input { margin-top:8px; }
        button { border:0; margin-top:14px; background:#2563eb; color:#fff; font-weight:700; cursor:pointer; touch-action: manipulation; }
        .f { margin-top:10px; font-size:13px; padding:8px 10px; border-radius:8px; }
        .ok { background:#ecfdf3; color:#166534; border:1px solid #bbf7d0; }
        .err { background:#fef2f2; color:#991b1b; border:1px solid #fecaca; }
      </style>
    </head>
    <body>
      <div class="box">
        <h2>🔐 ورود پنل وب</h2>
        <div class="muted">
          همان شماره‌ای که در ربات بله برای دیوار ثبت کرده‌اید و <b>رمز یک‌بار مصرف</b>ی که پس از اولین لاگین جدید موفق در ربات برایتان فرستاده می‌شود.
        </div>
        <form method="post">{{ probot_csrf_field()|safe }}
          <input type="tel" name="phone" inputmode="numeric" autocomplete="username" placeholder="مثال: 09123456789" required>
          <input type="password" name="password" autocomplete="current-password" placeholder="رمز پنل (از ربات بله)" required>
          <button type="submit">ورود</button>
        </form>
        {% for c,m in msgs %}
          <div class="f {{ c }}">{{ m }}</div>
        {% endfor %}
      </div>
    </body>
    </html>
    """
    return render_template_string(html, msgs=get_flashed_messages(with_categories=True))


@bp.route("/logout")
def logout():
    _clear_probot_session()
    return redirect(url_for(".login"), code=303)


@bp.route("/", methods=["GET"])
@login_required
def panel():
    cid = _panel_chatid()
    manage = curd.getManage(chatid=cid)
    stats = curd.getStats(chatid=cid)
    logins = curd.getLogins(chatid=cid)
    if not logins or logins == 0:
        logins = []
    recent_commands = curd.getRecentWebCommands(limit=25, chatid=cid)
    cfg = _load_raw_config()
    bale_status = _load_bale_status()
    message_logs = _load_web_message_logs(limit=40, panel_chatid=cid)
    nardeban_runtime = _get_nardeban_runtime_status()
    otp_phone = session.get("probot_otp_phone", "")
    open_otp_for_modal = bool(session.pop("probot_open_otp_modal", False))
    otp_pending_norm = _normalize_phone(otp_phone) if otp_phone else ""
    login_rows = []
    for t in logins:
        phone, cookie, active = t[0], t[1], t[2]
        row_norm = _normalize_phone(phone)
        login_rows.append(
            {
                "phone": phone,
                "cookie": cookie,
                "active": active,
                "can_otp_refresh": (not otp_pending_norm) or (row_norm == otp_pending_norm),
            }
        )
    weekday_names = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
    active_weekdays = cfg.get("active_weekdays", [0, 1, 2, 3, 4, 5, 6]) or []
    try:
        active_weekdays = sorted({int(d) for d in active_weekdays if 0 <= int(d) <= 6})
    except Exception:
        active_weekdays = [0, 1, 2, 3, 4, 5, 6]
    weekdays_text = "، ".join(weekday_names[d] for d in active_weekdays) if active_weekdays else "-"

    try:
        _nt = int(manage[3]) if manage and len(manage) > 3 and manage[3] is not None else 1
    except (TypeError, ValueError):
        _nt = 1
    if _nt not in (1, 2, 3, 4):
        _nt = 1
    current_nardeban_type = _nt
    nf_lo, nf_hi = natural_flow_range_minutes_from_manage_row(manage)
    nardeban_type_name = {1: "ترتیبی کامل", 2: "تصادفی", 3: "ترتیبی نوبتی", 4: "جریان طبیعی"}.get(
        current_nardeban_type, "ترتیبی کامل"
    )
    nardeban_type_options = [
        (1, "1️⃣ ترتیبی کامل هر لاگین"),
        (2, "2️⃣ تصادفی"),
        (3, "3️⃣ ترتیبی نوبتی"),
        (4, "🎢 4️⃣ جریان طبیعی"),
    ]
    admin_panel_rows = _admin_rows_for_panel() if DEFAULT_ADMIN_ID and cid == DEFAULT_ADMIN_ID else []
    is_primary_panel = bool(DEFAULT_ADMIN_ID and cid == DEFAULT_ADMIN_ID)

    html = """
    <!doctype html>
    <html lang="fa" dir="rtl">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
      <title>پنل ادمین ربات</title>
      <style>
        :root { color-scheme: dark; }
        *, *::before, *::after { box-sizing: border-box; }
        html { -webkit-text-size-adjust: 100%; }
        html, body { background:#020617 !important; color:#e5e7eb !important; overflow-x: hidden; }
        body {
          font-family: Tahoma, sans-serif; margin:0;
          padding: max(10px, env(safe-area-inset-top)) max(10px, env(safe-area-inset-right)) max(10px, env(safe-area-inset-bottom)) max(10px, env(safe-area-inset-left));
        }
        .wrap { max-width: 1280px; margin: 0 auto; padding: 0; width: 100%; }
        .top {
          display:flex; flex-direction: column; align-items: stretch; gap:12px; margin-bottom:12px;
          background: linear-gradient(135deg, #1d4ed8 0%, #7c3aed 50%, #0891b2 100%);
          border:1px solid #334155; border-radius:16px; padding:clamp(10px, 3vw, 14px);
          box-shadow: 0 10px 22px rgba(2, 6, 23, 0.45);
        }
        .brand { display:flex; align-items:center; gap:10px; min-width: 0; }
        .brand-badge {
          width:36px; height:36px; flex-shrink:0; border-radius:10px; display:flex; align-items:center; justify-content:center;
          background:rgba(255,255,255,0.16); border:1px solid rgba(255,255,255,0.28); font-size:18px;
        }
        .brand-text { min-width: 0; }
        .brand-text h2 { margin:0; font-size: clamp(15px, 4.2vw, 17px); color:#fff; line-height:1.3; }
        .brand-text .sub { color:#dbeafe; font-size:11px; margin-top:2px; line-height:1.35; }
        .header-clock {
          margin-top:8px; padding:7px 10px; border-radius:11px;
          background:rgba(2,6,23,0.32); border:1px solid rgba(255,255,255,0.22);
          max-width:100%; box-sizing:border-box;
        }
        .header-clock-time {
          font-family: ui-monospace, "Cascadia Mono", "Segoe UI Mono", Consolas, monospace;
          font-weight:700; font-size:clamp(15px, 4vw, 17px); color:#fff; letter-spacing:0.04em;
          line-height:1.25; font-variant-numeric: tabular-nums;
        }
        .header-clock-date {
          display:block; margin-top:3px; font-size:11px; color:#e0f2fe; line-height:1.45; opacity:0.96;
        }
        .header-clock-tz {
          display:block; margin-top:4px; font-size:10px; color:#bae6fd; opacity:0.88; letter-spacing:0.02em;
        }
        .top-right {
          display:flex; flex-direction: column; align-items: stretch; gap:8px; width:100%;
        }
        .pill {
          padding:8px 10px; border-radius:999px; font-size:11px; font-weight:700;
          background:rgba(2,6,23,0.35); border:1px solid rgba(255,255,255,0.26); color:#e2e8f0;
          text-align:center; word-break: break-word;
        }
        .pill.ok { color:#86efac; }
        .pill.warn { color:#fcd34d; }
        .top-action-form { margin:0; width:100%; }
        .top-action-btn {
          width:100%; min-width:0; min-height:44px; padding:10px 14px; border-radius:10px; border:1px solid rgba(255,255,255,0.24);
          background:rgba(2, 6, 23, 0.35) !important; color:#fff !important; font-weight:700; touch-action: manipulation;
        }
        .top-action-btn.gray { background:rgba(71,85,105,0.65) !important; border-color:rgba(148,163,184,0.45); }
        .top-action-btn:hover { background:rgba(2, 6, 23, 0.55) !important; }
        .btn-link {
          color:#fff; text-decoration:none; font-weight:700; padding:10px 14px; min-height:44px; border-radius:10px;
          background:rgba(2, 6, 23, 0.35); border:1px solid rgba(255,255,255,0.24);
          display:flex; align-items:center; justify-content:center; touch-action: manipulation;
        }
        .btn-link:hover { background:rgba(2, 6, 23, 0.52); }
        .grid3 { display:grid; grid-template-columns: 1fr; gap:12px; margin-bottom:12px; }
        .grid3 > .panel-details { margin-bottom: 0; }
        .grid2 { display:grid; grid-template-columns: 1fr; gap:12px; margin-top:12px; }
        .card { background:#0f172a !important; border:1px solid #334155; border-radius:14px; padding:clamp(10px, 3vw, 14px); min-width:0; }
        .card h3 { margin:2px 0 10px 0; font-size:clamp(15px, 3.8vw, 16px); }
        .row2 { display:grid; grid-template-columns: 1fr; gap:8px; }
        .row3 { display:grid; grid-template-columns: 1fr; gap:8px; }
        input,button { width:100%; box-sizing:border-box; padding:12px 12px; min-height:44px; border-radius:9px; border:1px solid #334155; background:#020617 !important; color:#e5e7eb !important; font-size:16px; }
        button { border:0; background:#2563eb; color:#fff; font-weight:700; cursor:pointer; touch-action: manipulation; }
        button.danger { background:#dc2626; }
        button.gray { background:#475569; }
        .kpi { display:grid; grid-template-columns: 1fr; gap:8px; }
        .item { background:#020617 !important; border:1px solid #334155; border-radius:10px; padding:10px; font-size:13px; word-break: break-word; }
        .item.clickable { cursor:pointer; transition:0.18s ease; -webkit-tap-highlight-color: transparent; }
        .item.clickable:hover { border-color:#60a5fa; transform:translateY(-1px); }
        .item-title { color:#93c5fd; font-size:12px; margin-bottom:4px; }
        .nardeban-type-grid { display:flex; flex-direction:column; gap:8px; margin-top:8px; }
        .nardeban-type-grid form { margin:0; }
        .nardeban-type-btn {
          width:100%; text-align:right; padding:10px 12px; min-height:44px; box-sizing:border-box;
          background:#0f172a !important; border:1px solid #334155; border-radius:10px;
          color:#e5e7eb !important; font-weight:600; font-size:13px; cursor:pointer; touch-action: manipulation;
        }
        .nardeban-type-btn:hover { border-color:#60a5fa; }
        .nardeban-type-btn--active {
          border-color:#60a5fa !important; box-shadow:0 0 0 1px rgba(96,165,250,0.35);
          background:#0c1929 !important;
        }
        .nardeban-type-btn:disabled {
          opacity:1; cursor:default;
        }
        .nardeban-type-help { margin-top:10px; font-size:12px; color:#94a3b8; }
        .nardeban-type-help > summary {
          cursor:pointer; color:#93c5fd; font-weight:600; list-style:none; user-select:none;
          -webkit-tap-highlight-color: transparent;
        }
        .nardeban-type-help > summary::-webkit-details-marker { display:none; }
        .nardeban-type-help-body { margin-top:8px; line-height:1.55; color:#cbd5e1; }
        .nardeban-type-help-body p { margin:0 0 8px 0; }
        .log-list { max-height: min(220px, 40vh); overflow:auto; -webkit-overflow-scrolling: touch; display:flex; flex-direction:column; gap:8px; margin-top:8px; }
        .log-row { background:#020617; border:1px solid #334155; border-radius:10px; padding:8px; font-size:12px; }
        .log-row .log-body { white-space: pre-wrap; word-break: break-word; }
        .log-time { color:#93c5fd; font-size:11px; margin-bottom:4px; }
        .panel-details { background:#0f172a !important; border:1px solid #334155; border-radius:14px; margin-bottom:12px; overflow:hidden; }
        .panel-details > summary {
          list-style:none; cursor:pointer; padding:12px 12px; font-weight:700; font-size:clamp(13px, 3.5vw, 15px);
          display:flex; align-items:center; justify-content:space-between; gap:8px;
          background:#020617; color:#e5e7eb; user-select:none; -webkit-tap-highlight-color: transparent;
        }
        .panel-details > summary span:first-child { min-width:0; text-align:right; }
        .panel-details > summary::-webkit-details-marker { display:none; }
        .panel-details[open] > summary { border-bottom:1px solid #334155; }
        .panel-details > summary .chev { color:#93c5fd; font-size:12px; flex-shrink:0; transition:transform 0.2s; }
        .panel-details[open] > summary .chev { transform:rotate(-90deg); }
        .panel-details-inner { padding:clamp(8px, 2.5vw, 12px); }
        .table-wrap { width:100%; overflow-x:auto; -webkit-overflow-scrolling: touch; margin-top:8px; border-radius:10px; border:1px solid #334155; }
        .table-wrap table { margin-top:0; min-width: 400px; }
        .table-wrap--wide table { min-width: 680px; }
        table { width:100%; border-collapse:collapse; background:#0f172a !important; border:1px solid #334155; }
        th,td { border:1px solid #334155; padding:8px; font-size:12px; vertical-align:top; }
        .table-wrap .td-actions { display:flex; flex-direction:column; gap:6px; align-items:stretch; }
        @media (min-width: 520px) {
          .table-wrap .td-actions { flex-direction:row; flex-wrap:wrap; align-items:center; }
          .table-wrap .td-actions form { flex:1; min-width: 88px; }
        }
        .table-wrap .td-actions button { min-height:40px; font-size:14px; }
        .f { margin-top:8px; font-size:13px; padding:8px 10px; border-radius:8px; }
        .ok { background:#ecfdf3; color:#166534; border:1px solid #bbf7d0; }
        .err { background:#fef2f2; color:#991b1b; border:1px solid #fecaca; }
        .modal-backdrop {
          display:none; position:fixed; inset:0; background:rgba(2,6,23,0.72);
          align-items:flex-end; justify-content:center; z-index:9999;
          padding: max(10px, env(safe-area-inset-bottom)) max(10px, env(safe-area-inset-left)) max(10px, env(safe-area-inset-right));
        }
        .modal-backdrop.show { display:flex; }
        @media (min-width: 520px) {
          .modal-backdrop { align-items:center; padding:14px; }
        }
        .modal-card {
          width:100%; max-width:420px; max-height: min(90vh, 100dvh - 24px); overflow-y:auto; -webkit-overflow-scrolling: touch;
          background:#0f172a; border:1px solid #334155; border-radius:14px 14px 0 0; padding:14px;
        }
        @media (min-width: 520px) {
          .modal-card { border-radius:14px; }
        }
        .modal-title { margin:0 0 8px 0; color:#bfdbfe; font-size:15px; }
        .modal-actions { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
        .modal-muted { margin:0 0 10px 0; font-size:13px; color:#94a3b8; line-height:1.45; }
        .login-toolbar { display:flex; flex-direction:column; gap:8px; margin-bottom:12px; }
        .login-toolbar .btn-secondary {
          width:100%; min-height:44px; padding:10px 14px; border-radius:10px; border:1px solid #475569;
          background:#1e293b !important; color:#e2e8f0 !important; font-weight:700; cursor:pointer; touch-action: manipulation;
        }
        .login-toolbar .btn-secondary:hover { background:#334155 !important; }
        .weekday-grid { display:grid; grid-template-columns: 1fr; gap:8px; margin-top:10px; }
        .wd-label {
          display:flex; align-items:center; gap:8px; padding:8px 10px; background:#020617; border:1px solid #334155;
          border-radius:10px; cursor:pointer; font-size:13px; user-select:none;
        }
        .wd-label:hover { border-color:#60a5fa; }
        .wd-label input[type=checkbox] { width:auto !important; min-width:20px; height:20px; margin:0; accent-color:#2563eb; cursor:pointer; }
        @media (min-width: 400px) {
          .kpi { grid-template-columns: 1fr 1fr; }
          .row2 { grid-template-columns: 1fr 1fr; }
          .weekday-grid { grid-template-columns: 1fr 1fr; }
        }
        @media (min-width: 640px) {
          .grid3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .top { flex-direction: row; align-items: center; flex-wrap: wrap; }
          .top-right {
            flex-direction: row; flex-wrap: wrap; align-items: center; justify-content: flex-end;
            width: auto; flex: 1; min-width: min(100%, 280px);
          }
          .top-action-form { width: auto; }
          .top-action-btn { width: auto; min-width: 130px; }
          .pill { font-size: 12px; text-align: inherit; }
          .brand-text .sub { font-size: 12px; }
        }
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="top">
          <div class="brand">
            <div class="brand-badge">⚡</div>
              <div class="brand-text">
              <h2>مرکز کنترل ربات</h2>
              <div class="sub">شناسهٔ شما در بله: <b>{{ panel_chatid }}</b> · مدیریت وب همگام با همان حساب</div>
              <div class="header-clock" id="header-clock" aria-live="polite" aria-atomic="true">
                <span class="header-clock-time" id="hdr-time">--:--:--</span>
                <span class="header-clock-date" id="hdr-date">…</span>
                <span class="header-clock-tz">ساعت تهران (ایران) · تقویم شمسی</span>
              </div>
            </div>
          </div>
          <div class="top-right">
            {% if nardeban_runtime.active_jobs_count > 0 %}
            <form method="post" action="{{ probot_prefix }}/api/command" class="top-action-form">{{ probot_csrf_field()|safe }}
              <input type="hidden" name="command_type" value="remJob">
              <button type="submit" class="top-action-btn gray">توقف نردبان</button>
            </form>
            {% elif nardeban_runtime.start_command_in_flight %}
            <div class="top-action-form">
              <button type="button" class="top-action-btn gray" disabled style="opacity:0.88;cursor:not-allowed;">در حال شروع نردبان…</button>
            </div>
            {% else %}
            <form method="post" action="{{ probot_prefix }}/api/command" class="top-action-form">{{ probot_csrf_field()|safe }}
              <input type="hidden" name="command_type" value="startJob">
              <button type="submit" class="top-action-btn">شروع نردبان</button>
            </form>
            {% endif %}
            <span class="pill">ربات بله: {{ bale_status.get("state", "unknown") }}</span>
            <a class="btn-link" href="{{ probot_prefix }}/logout">خروج</a>
          </div>
        </div>

        {% for c,m in flashes %}
          <div class="f {{ c }}">{{ m }}</div>
        {% endfor %}

        <div class="grid3">
          <details class="panel-details" open>
            <summary>
              <span>🎛️ وضعیت</span>
              <span class="chev">◀</span>
            </summary>
            <div class="panel-details-inner">
              <button type="button" class="item clickable" onclick="openModal('m-active')"><div class="item-title">وضعیت ربات</div><b>{{ "فعال" if manage[0] == 1 else "غیرفعال" }}</b></button>
              <button type="button" class="item clickable" onclick="openModal('m-type')"><div class="item-title">نوع نردبان</div><b>{{ nardeban_type_name }}</b> <span style="opacity:.85;font-size:13px;">({{ current_nardeban_type }})</span></button>
              <button type="button" class="item clickable" onclick="openModal('m-interval')"><div class="item-title">فاصله</div><b>{{ manage[5] }} دقیقه</b></button>
              <button type="button" class="item clickable" onclick="openModal('m-nf-range')"><div class="item-title">بازهٔ جریان طبیعی</div><b>{{ nf_lo }}–{{ nf_hi }} دقیقه</b></button>
              {% if is_primary_panel %}
              <button type="button" class="item clickable" onclick="openModal('m-start')"><div class="item-title">شروع</div><b>{{ cfg.get("start_hour","-") }}:{{ "%02d"|format(cfg.get("start_minute",0)) }}</b></button>
              <button type="button" class="item clickable" onclick="openModal('m-stop')"><div class="item-title">توقف</div><b>{{ cfg.get("stop_hour","-") }}:{{ "%02d"|format(cfg.get("stop_minute",0)) }}</b></button>
              <button type="button" class="item clickable" onclick="openModal('m-repeat')"><div class="item-title">تکرار</div><b>{{ cfg.get("repeat_days", "-") }} روز</b></button>
              <button type="button" class="item clickable" onclick="openModal('m-weekdays')"><div class="item-title">روزهای فعال</div><b>{{ weekdays_text }}</b></button>
              {% else %}
              <div class="item" style="font-size:12px;color:#94a3b8;">ساعت شروع/توقف، تکرار و روزهای هفتهٔ <b>سراسری</b> فقط با حساب ادمین اصلی قابل تغییر است؛ بقیهٔ تنظیمات همان ربات بلهٔ شماست.</div>
              {% endif %}
              <div class="item">آخرین بروزرسانی: <b>{{ bale_status.get("updated_at", "-") }}</b></div>
              <div class="item">وضعیت اجرای نردبان: <b>{{ nardeban_runtime.state_text }}</b></div>
              <div class="item">تعداد job فعال نردبان: <b>{{ nardeban_runtime.active_jobs_count }}</b></div>
              <div class="item">شناسه job فعال: <b>{{ nardeban_runtime.job_id }}</b></div>
              <div class="item">در صف شروع: <b>{{ nardeban_runtime.pending_start }}</b> | در صف توقف: <b>{{ nardeban_runtime.pending_stop }}</b></div>
            </div>
          </details>

          <details class="panel-details" open>
            <summary>
              <span>📊 آمار و لاگ پیام‌ها</span>
              <span class="chev">◀</span>
            </summary>
            <div class="panel-details-inner">
              <div class="kpi">
                <div class="item">کل نردبان: <b>{{ stats.total_nardeban }}</b></div>
                <div class="item">کل توکن: <b>{{ stats.total_tokens }}</b></div>
                <div class="item">در انتظار: <b>{{ stats.total_pending }}</b></div>
                <div class="item">ناموفق: <b>{{ stats.total_failed }}</b></div>
              </div>
              <div class="row2" style="margin-top:8px;">
                <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
                  <input type="hidden" name="command_type" value="reExtract">
                  <button>استخراج مجدد</button>
                </form>
                <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
                  <input type="hidden" name="command_type" value="resetTokens">
                  <button class="danger">ریست کامل</button>
                </form>
              </div>
              <div class="log-list">
                {% if message_logs %}
                  {% for lg in message_logs %}
                    <div class="log-row">
                      <div class="log-time">{{ lg.ts }}</div>
                      <div class="log-body">{{ lg.text }}</div>
                    </div>
                  {% endfor %}
                {% else %}
                  <div class="item">هنوز لاگی ثبت نشده است.</div>
                {% endif %}
              </div>
            </div>
          </details>

        </div>

        <details class="panel-details">
          <summary>
            <span>🧾 صف فرمان‌ها <span style="font-weight:400;color:#94a3b8;font-size:13px;">({{ recent_commands|length }} مورد اخیر)</span></span>
            <span class="chev">◀</span>
          </summary>
          <div class="panel-details-inner">
            <div class="table-wrap table-wrap--wide">
            <table>
              <tr><th>ID</th><th>نوع</th><th>وضعیت</th><th>نتیجه</th><th>ایجاد</th><th>پردازش</th></tr>
              {% for row in recent_commands %}
              <tr>
                <td>{{ row[0] }}</td>
                <td>{{ row[2] }}</td>
                <td>{{ row[4] }}</td>
                <td>{{ row[5] or "-" }}</td>
                <td>{{ row[6] or "-" }}</td>
                <td>{{ row[7] or "-" }}</td>
              </tr>
              {% endfor %}
            </table>
            </div>
          </div>
        </details>

        {% if is_primary_panel %}
        <details class="panel-details">
          <summary>
            <span>👥 مدیریت ادمین‌ها <span style="font-weight:400;color:#94a3b8;font-size:13px;">({{ admin_panel_rows|length }} نفر)</span></span>
            <span class="chev">◀</span>
          </summary>
          <div class="panel-details-inner">
            <div class="item" style="margin-bottom:10px;font-size:12px;color:#94a3b8;line-height:1.45;">
              ⭐ همان ادمین پیش‌فرض configs است و قابل حذف نیست. 🗣 ادمین‌های اضافه‌شده از بله یا همینجا؛ پس از افزودن، کاربر باید در ربات <b>/start</b> بزند.
            </div>
            <div class="table-wrap">
            <table>
              <tr><th>شناسه چت</th><th>نقش</th><th>اکشن</th></tr>
              {% for row in admin_panel_rows %}
              <tr>
                <td>{{ row.id }}</td>
                <td>{{ "⭐ پیش‌فرض" if row.is_primary else "🗣 ادمین" }}</td>
                <td class="td-actions">
                  {% if not row.is_primary %}
                  <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
                    <input type="hidden" name="command_type" value="removeAdmin">
                    <input type="hidden" name="admin_chat_id" value="{{ row.id }}">
                    <button type="submit" class="danger">حذف</button>
                  </form>
                  {% else %}
                  <span style="font-size:12px;color:#64748b;">🔒</span>
                  {% endif %}
                </td>
              </tr>
              {% endfor %}
            </table>
            </div>
            <h4 style="margin:12px 0 6px 0; font-size:14px; color:#cbd5e1;">افزودن ادمین</h4>
            <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
              <input type="hidden" name="command_type" value="addAdmin">
              <input type="text" name="admin_chat_id" inputmode="numeric" pattern="[0-9]+" placeholder="شناسه چت تلگرام (مثال: 123456789)" required>
              <button type="submit" style="margin-top:8px;">افزودن به لیست</button>
            </form>
          </div>
        </details>
        {% endif %}

        <details class="panel-details">
          <summary>
            <span>📱 لاگین‌ها و OTP دیوار <span style="font-weight:400;color:#94a3b8;font-size:13px;">({{ login_rows|length }} شماره)</span></span>
            <span class="chev">◀</span>
          </summary>
          <div class="panel-details-inner">
            <div class="login-toolbar">
              {% if not otp_phone %}
              <button type="button" class="btn-secondary" onclick="openModal('m-otp')">🔐 ورود / افزودن لاگین با OTP دیوار</button>
              {% else %}
              <div class="item" style="margin:0;font-size:12px;">⏳ فرآیند OTP برای <b>{{ otp_phone }}</b> باز است؛ ابتدا کد را وارد یا لغو کنید. شروع فرآیند جدید با شمارهٔ دیگر ممکن نیست.</div>
              {% endif %}
              {% if otp_phone %}
              <button type="button" class="btn-secondary" onclick="openModal('m-otp')">✉️ ادامه: وارد کردن کد برای {{ otp_phone }}</button>
              {% endif %}
            </div>
            <p class="modal-muted" style="margin-bottom:12px;">{% if otp_phone %}فقط همان شماره می‌تواند دوباره درخواست کد (ارسال مجدد) بگیرد؛ بقیه تا پایان فرآیند قفل هستند.{% else %}برای هر شماره با <b>بروزرسانی</b> می‌توانید کد بگیرید و کوکی را مثل تلگرام تمدید کنید.{% endif %}</p>
            <h4 style="margin:8px 0 6px 0; font-size:14px; color:#cbd5e1;">لیست لاگین‌ها</h4>
            <div class="table-wrap">
            <table>
              <tr><th>شماره</th><th>وضعیت</th><th>اکشن</th></tr>
              {% for row in login_rows %}
              <tr>
                <td>{{ row.phone }}</td>
                <td>{{ "فعال" if row.active == 1 else "غیرفعال" }}</td>
                <td class="td-actions">
                  <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
                    <input type="hidden" name="command_type" value="setLoginActive">
                    <input type="hidden" name="phone" value="{{ row.phone }}">
                    <input type="hidden" name="active" value="{{ 0 if row.active == 1 else 1 }}">
                    <button>{{ "غیرفعال" if row.active == 1 else "فعال" }}</button>
                  </form>
                  <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
                    <input type="hidden" name="command_type" value="deleteLogin">
                    <input type="hidden" name="phone" value="{{ row.phone }}">
                    <button class="danger">حذف</button>
                  </form>
                  {% if row.can_otp_refresh %}
                  <form method="post" action="{{ probot_prefix }}/otp/request">{{ probot_csrf_field()|safe }}
                    <input type="hidden" name="phone" value="{{ row.phone }}">
                    <button type="submit" class="gray" title="ارسال کد OTP برای تمدید کوکی">🔄 {% if otp_phone %}ارسال مجدد{% else %}بروزرسانی{% endif %}</button>
                  </form>
                  {% else %}
                  <button type="button" class="gray" disabled title="ابتدا فرآیند OTP فعلی را تمام کنید">🔒 بروزرسانی</button>
                  {% endif %}
                </td>
              </tr>
              {% endfor %}
            </table>
            </div>
          </div>
        </details>
      </div>

      <div id="m-otp" class="modal-backdrop" onclick="closeModal(event, 'm-otp')">
        <div class="modal-card" onclick="event.stopPropagation()">
          <h4 class="modal-title">🔐 OTP دیوار — ورود یا به‌روزرسانی لاگین</h4>
          {% if otp_phone %}
            <p class="modal-muted">کد تأیید به شماره <b>{{ otp_phone }}</b> ارسال شده است. کد را وارد کنید.</p>
            <form method="post" action="{{ probot_prefix }}/otp/confirm">{{ probot_csrf_field()|safe }}
              <input type="text" name="code" placeholder="کد OTP" required inputmode="numeric" autocomplete="one-time-code">
              <button type="submit" style="margin-top:10px;">تایید و ثبت / به‌روزرسانی لاگین</button>
            </form>
            <form method="post" action="{{ probot_prefix }}/otp/request" style="margin-top:8px;">{{ probot_csrf_field()|safe }}
              <input type="hidden" name="phone" value="{{ otp_phone }}">
              <button type="submit" class="gray">📨 ارسال مجدد کد پیامک</button>
            </form>
            <form method="post" action="{{ probot_prefix }}/otp/cancel" style="margin-top:10px;">{{ probot_csrf_field()|safe }}
              <button type="submit" class="gray">لغو و شمارهٔ دیگر</button>
            </form>
          {% else %}
            <p class="modal-muted">شماره موبایل همان حساب دیوار را وارد کنید؛ پس از دریافت پیامک، کد را در همین پنجره وارد می‌کنید.</p>
            <form method="post" action="{{ probot_prefix }}/otp/request">{{ probot_csrf_field()|safe }}
              <input type="text" name="phone" placeholder="09xxxxxxxxx" required inputmode="tel" autocomplete="tel">
              <button type="submit" style="margin-top:10px;">ارسال کد</button>
            </form>
            <button type="button" class="gray" style="margin-top:10px;width:100%;" onclick="closeModal({ target: document.getElementById('m-otp') }, 'm-otp')">بستن</button>
          {% endif %}
        </div>
      </div>

      <div id="m-active" class="modal-backdrop" onclick="closeModal(event, 'm-active')">
        <div class="modal-card">
          <h4 class="modal-title">تنظیم وضعیت ربات</h4>
          <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
            <input type="hidden" name="command_type" value="setactive">
            <input type="hidden" name="active" value="{{ 0 if manage[0] == 1 else 1 }}">
            <button class="{{ 'danger' if manage[0] == 1 else '' }}">{{ "خاموش کردن ربات" if manage[0] == 1 else "روشن کردن ربات" }}</button>
          </form>
        </div>
      </div>

      <div id="m-interval" class="modal-backdrop" onclick="closeModal(event, 'm-interval')">
        <div class="modal-card">
          <h4 class="modal-title">تنظیم فاصله</h4>
          <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
            <input type="hidden" name="command_type" value="setInterval">
            <input type="number" min="1" name="interval_minutes" placeholder="فاصله (دقیقه)" required>
            <button style="margin-top:8px;">ثبت</button>
          </form>
        </div>
      </div>

      <div id="m-nf-range" class="modal-backdrop" onclick="closeModal(event, 'm-nf-range')">
        <div class="modal-card" onclick="event.stopPropagation()">
          <h4 class="modal-title">بازهٔ جریان طبیعی (دقیقه)</h4>
          <p class="modal-muted">حداقل و حداکثر فاصلهٔ تصادفی بین دو نردبان در نوع «جریان طبیعی»؛ هر عدد ۱ تا ۱۴۴۰.</p>
          <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
            <input type="hidden" name="command_type" value="setNaturalFlowRange">
            <input type="number" min="1" max="1440" name="natural_flow_min_minutes" placeholder="حداقل (دقیقه)" required>
            <input type="number" min="1" max="1440" name="natural_flow_max_minutes" placeholder="حداکثر (دقیقه)" required style="margin-top:8px;">
            <button type="submit" style="margin-top:8px;">ثبت</button>
          </form>
          <button type="button" class="gray" style="margin-top:10px;width:100%;" onclick="closeModal({ target: document.getElementById('m-nf-range') }, 'm-nf-range')">بستن</button>
        </div>
      </div>

      <div id="m-type" class="modal-backdrop" onclick="closeModal(event, 'm-type')">
        <div class="modal-card" onclick="event.stopPropagation()">
          <h4 class="modal-title">تنظیم نوع نردبان</h4>
          <p class="modal-muted">نوع فعلی: <b>{{ nardeban_type_name }}</b> <span style="opacity:.9">({{ current_nardeban_type }})</span> — یکی از گزینه‌ها را انتخاب کنید تا در صف ثبت شود.</p>
          <div class="nardeban-type-grid">
            {% for val, label in nardeban_type_options %}
            {% if val == current_nardeban_type %}
            <div>
              <button type="button" disabled class="nardeban-type-btn nardeban-type-btn--active">✅ {{ label }}</button>
            </div>
            {% else %}
            <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
              <input type="hidden" name="command_type" value="setNardebanType">
              <input type="hidden" name="nardeban_type" value="{{ val }}">
              <button type="submit" class="nardeban-type-btn">⚪ {{ label }}</button>
            </form>
            {% endif %}
            {% endfor %}
          </div>
          <details class="nardeban-type-help" style="margin-top:12px;">
            <summary>راهنمای انواع</summary>
            <div class="nardeban-type-help-body">
              <p><b>1️⃣ ترتیبی کامل هر لاگین:</b> هر لاگین → همه آگهی‌هاش کامل نردبان می‌شود → بعد لاگین بعدی</p>
              <p><b>2️⃣ تصادفی:</b> در هر بار اجرا، یک آگهی تصادفی از بین همه لاگین‌ها انتخاب و نردبان می‌شود</p>
              <p><b>3️⃣ ترتیبی نوبتی:</b> از هر لاگین فقط یک آگهی → لاگین بعدی → تا تمام شدن آگهی‌ها</p>
              <p><b>🎢 4️⃣ جریان طبیعی:</b> آگهی‌های قدیمی‌تر و کم‌بازدیدتر اولویت می‌گیرند؛ فاصلهٔ زمانی نامنظم؛ بازهٔ دقیقه از کارت «بازهٔ جریان طبیعی» در همین پنل تنظیم می‌شود (فعلی: {{ nf_lo }}–{{ nf_hi }}).</p>
            </div>
          </details>
          <button type="button" class="gray" style="margin-top:12px;width:100%;" onclick="closeModal({ target: document.getElementById('m-type') }, 'm-type')">بستن</button>
        </div>
      </div>

      {% if is_primary_panel %}
      <div id="m-start" class="modal-backdrop" onclick="closeModal(event, 'm-start')">
        <div class="modal-card">
          <h4 class="modal-title">تنظیم زمان شروع</h4>
          <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
            <input type="hidden" name="command_type" value="setStartTime">
            <input type="text" name="time_text" placeholder="شروع HH:MM" required>
            <button style="margin-top:8px;">ثبت</button>
          </form>
        </div>
      </div>

      <div id="m-stop" class="modal-backdrop" onclick="closeModal(event, 'm-stop')">
        <div class="modal-card">
          <h4 class="modal-title">تنظیم زمان توقف</h4>
          <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
            <input type="hidden" name="command_type" value="setStopTime">
            <input type="text" name="time_text" placeholder="توقف HH:MM" required>
            <button style="margin-top:8px;">ثبت</button>
          </form>
        </div>
      </div>

      <div id="m-repeat" class="modal-backdrop" onclick="closeModal(event, 'm-repeat')">
        <div class="modal-card">
          <h4 class="modal-title">تنظیم تکرار</h4>
          <form method="post" action="{{ probot_prefix }}/api/command">{{ probot_csrf_field()|safe }}
            <input type="hidden" name="command_type" value="setRepeatDays">
            <input type="number" min="1" max="3650" name="repeat_days" placeholder="تکرار (روز)" required>
            <button style="margin-top:8px;">ثبت</button>
          </form>
        </div>
      </div>

      <div id="m-weekdays" class="modal-backdrop" onclick="closeModal(event, 'm-weekdays')">
        <div class="modal-card" onclick="event.stopPropagation()">
          <h4 class="modal-title">تنظیم روزهای فعال</h4>
          <p style="margin:0 0 6px 0; font-size:12px; color:#94a3b8;">روزهایی که نردبان خودکار در آن‌ها مجاز است را انتخاب کنید.</p>
          <form method="post" action="{{ probot_prefix }}/api/command" onsubmit="return buildWeekdaysSubmit(this);">{{ probot_csrf_field()|safe }}
            <input type="hidden" name="command_type" value="setWeekdays">
            <input type="hidden" name="weekdays" id="inp-weekdays-combined" value="">
            <div class="weekday-grid">
              {% for i in [0,1,2,3,4,5,6] %}
              <label class="wd-label">
                <input type="checkbox" class="wd-cb" value="{{ i }}" {% if i in active_weekdays %}checked{% endif %}>
                <span>{{ weekday_names[i] }}</span>
              </label>
              {% endfor %}
            </div>
            <button type="submit" style="margin-top:12px;">ثبت</button>
          </form>
        </div>
      </div>
      {% endif %}

      <script>
        function openModal(id) {
          var m = document.getElementById(id);
          if (m) m.classList.add("show");
        }
        function closeModal(e, id) {
          if (!e || e.target.id === id) {
            var m = document.getElementById(id);
            if (m) m.classList.remove("show");
          }
        }
        function buildWeekdaysSubmit(form) {
          var boxes = form.querySelectorAll("input.wd-cb:checked");
          if (!boxes.length) {
            alert("حداقل یک روز را انتخاب کنید.");
            return false;
          }
          var vals = Array.prototype.map.call(boxes, function (b) { return b.value; });
          vals.sort(function (a, b) { return Number(a) - Number(b); });
          var hidden = form.querySelector("#inp-weekdays-combined");
          if (hidden) hidden.value = vals.join(",");
          return true;
        }
        /* پس از هر POST داخل پنل، ناوبری صریح برای جلوگیری از کش و نمایش دادهٔ تازه */
        document.addEventListener("submit", function (e) {
          if (e.defaultPrevented) return;
          var f = e.target;
          if (!(f instanceof HTMLFormElement) || String(f.method || "").toLowerCase() !== "post") return;
          if (!f.closest(".wrap")) return;
          var act = (f.getAttribute("action") || "").trim();
          /* OTP: ناوبری واقعی مرورگر تا سشن/فلش و باز شدن مودال بعد از ریدایرکت درست کار کند */
          if (act.indexOf("/otp/") !== -1) return;
          e.preventDefault();
          var url = act ? new URL(act, window.location.origin).href : window.location.href;
          fetch(url, {
            method: "POST",
            body: new FormData(f),
            credentials: "same-origin",
            redirect: "manual"
          }).then(function (r) {
            var loc = r.headers.get("Location");
            if (loc && r.status >= 300 && r.status < 400) {
              window.location.href = new URL(loc, window.location.origin).href;
              return;
            }
            window.location.reload();
          }).catch(function () { window.location.reload(); });
        }, false);
        window.addEventListener("pageshow", function (ev) {
          if (ev.persisted) window.location.reload();
        });
        (function headerClockTehran() {
          var TZ = "Asia/Tehran";
          var elT = document.getElementById("hdr-time");
          var elD = document.getElementById("hdr-date");
          if (!elT || !elD) return;
          var fmtTime = new Intl.DateTimeFormat("fa-IR", {
            timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
          });
          var fmtDate;
          try {
            fmtDate = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
              timeZone: TZ, weekday: "long", year: "numeric", month: "long", day: "numeric"
            });
          } catch (e1) {
            try {
              fmtDate = new Intl.DateTimeFormat("fa-IR", { timeZone: TZ, calendar: "persian",
                weekday: "long", year: "numeric", month: "long", day: "numeric" });
            } catch (e2) {
              fmtDate = new Intl.DateTimeFormat("fa-IR", {
                timeZone: TZ, weekday: "long", year: "numeric", month: "long", day: "numeric"
              });
            }
          }
          function tick() {
            var now = new Date();
            elT.textContent = fmtTime.format(now);
            elD.textContent = fmtDate.format(now);
          }
          tick();
          setInterval(tick, 1000);
        })();
        {% if open_otp_for_modal %}
        document.addEventListener("DOMContentLoaded", function () { openModal("m-otp"); });
        {% endif %}
      </script>
    </body>
    </html>
    """
    resp = make_response(
        render_template_string(
            html,
            manage=manage,
            stats=stats,
            logins=logins,
            login_rows=login_rows,
            recent_commands=recent_commands,
            cfg=cfg,
            bale_status=bale_status,
            message_logs=message_logs,
            nardeban_runtime=nardeban_runtime,
            weekdays_text=weekdays_text,
            weekday_names=weekday_names,
            active_weekdays=active_weekdays,
            otp_phone=otp_phone,
            open_otp_for_modal=open_otp_for_modal,
            current_nardeban_type=current_nardeban_type,
            nf_lo=nf_lo,
            nf_hi=nf_hi,
            nardeban_type_name=nardeban_type_name,
            nardeban_type_options=nardeban_type_options,
            admin_panel_rows=admin_panel_rows,
            is_primary_panel=is_primary_panel,
            panel_chatid=cid,
            flashes=get_flashed_messages(with_categories=True),
        )
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@bp.route("/otp/request", methods=["POST"])
@login_required
def otp_request():
    pending = _normalize_phone(session.get("probot_otp_phone") or "")
    phone = _normalize_phone(request.form.get("phone"))
    if not phone:
        flash("شماره موبایل وارد نشده است.", "err")
        return redirect(url_for(".panel"), code=303)
    if pending and phone != pending:
        flash(
            "یک فرآیند تأیید OTP هنوز باز است؛ ابتدا برای همان شماره کد را وارد کنید یا «لغو و شمارهٔ دیگر» را بزنید. تا آن زمان نمی‌توانید برای شمارهٔ دیگر کد بگیرید.",
            "err",
        )
        session["probot_open_otp_modal"] = True
        session.modified = True
        return redirect(url_for(".panel"), code=303)
    if not (phone.startswith("09") and len(phone) == 11 and phone.isdigit()):
        flash("شماره موبایل معتبر نیست. مثال: 09123456789", "err")
        return redirect(url_for(".panel"), code=303)
    try:
        response = divar_api.login(phone=phone)
        if isinstance(response, dict) and response.get("error"):
            flash(f"خطا در ارسال کد: {response.get('error')}", "err")
        elif isinstance(response, dict) and response.get("http_status", 200) >= 400:
            flash(f"خطا از دیوار: {response}", "err")
        else:
            session["probot_otp_phone"] = phone
            session["probot_open_otp_modal"] = True
            session.modified = True
            flash(f"کد برای شماره {phone} ارسال شد؛ کد را در پنجره وارد کنید.", "ok")
    except Exception as e:
        flash(f"خطا در ارسال OTP: {e}", "err")
    return redirect(url_for(".panel"), code=303)


@bp.route("/otp/cancel", methods=["POST"])
@login_required
def otp_cancel():
    session.pop("probot_otp_phone", None)
    session.pop("probot_open_otp_modal", None)
    flash("فرآیند OTP لغو شد.", "ok")
    return redirect(url_for(".panel"), code=303)


@bp.route("/otp/confirm", methods=["POST"])
@login_required
def otp_confirm():
    phone = _normalize_phone(session.get("probot_otp_phone") or request.form.get("phone"))
    code = (request.form.get("code") or "").strip()
    if not phone:
        flash("ابتدا شماره را وارد کرده و روی «ارسال کد» بزنید.", "err")
        return redirect(url_for(".panel"), code=303)
    if not code:
        flash("کد OTP الزامی است.", "err")
        return redirect(url_for(".panel"), code=303)
    if not (phone.startswith("09") and len(phone) == 11 and phone.isdigit()):
        flash("شماره موبایل معتبر نیست.", "err")
        return redirect(url_for(".panel"), code=303)
    if not code.isdigit():
        flash("کد OTP باید عدد باشد.", "err")
        return redirect(url_for(".panel"), code=303)

    try:
        response = divar_api.verifyOtp(phone=phone, code=code)
        token = response.get("token") if isinstance(response, dict) else None
        if not token:
            if isinstance(response, dict) and response.get("error"):
                flash(f"OTP ناموفق: {response.get('error')}", "err")
            else:
                flash(f"OTP ناموفق: {response}", "err")
            return redirect(url_for(".panel"), code=303)

        cid = _panel_chatid()
        stored_cookie = pack_login_cookie(response)
        add_rc = curd.addLogin(chatid=cid, phone=phone, cookie=stored_cookie)
        if add_rc == 0:
            curd.updateLogin(phone=phone, cookie=stored_cookie, chatid=cid)
            flash(
                f"ورود مجدد دیوار برای {phone} انجام شد؛ کوکی جایگزین شد و این لاگین فعال است.",
                "ok",
            )
        else:
            if not curd.has_web_panel_password(cid):
                try:
                    plain = curd.issue_web_panel_password(cid)
                    flash(
                        f"لاگین جدید ثبت شد. رمز ورود پنل وب (با همین شماره): {plain}",
                        "ok",
                    )
                except Exception as e:
                    flash(f"لاگین ثبت شد اما صدور رمز پنل ناموفق بود: {e}", "err")
            else:
                flash("لاگین جدید ثبت شد. برای ورود وب از همان رمز پنلی که قبلاً دریافت کرده‌اید استفاده کنید.", "ok")
        session.pop("probot_otp_phone", None)
        session.pop("probot_open_otp_modal", None)
        session.modified = True
    except Exception as e:
        flash(f"خطا در تایید OTP: {e}", "err")
    return redirect(url_for(".panel"), code=303)


@bp.route("/api/command", methods=["POST"])
@login_required
def api_command():
    command_type = (request.form.get("command_type") or "").strip()
    if not command_type:
        flash("نوع فرمان مشخص نیست.", "err")
        return redirect(url_for(".panel"), code=303)

    payload = {}
    for key in [
        "active",
        "interval_minutes",
        "natural_flow_min_minutes",
        "natural_flow_max_minutes",
        "nardeban_type",
        "time_text",
        "repeat_days",
        "weekdays",
        "phone",
        "admin_chat_id",
    ]:
        value = request.form.get(key)
        if value is not None and str(value).strip() != "":
            payload[key] = str(value).strip()

    cid = _panel_chatid()
    if command_type == "startJob":
        if curd.getJob(chatid=cid):
            flash(
                "یک نردبان از قبل فعال است — مثل تلگرام نمی‌توانید دوباره شروع کنید. ابتدا «توقف نردبان» را بزنید.",
                "err",
            )
            return redirect(url_for(".panel"), code=303)
        if curd.has_web_command_in_flight(cid, "startJob"):
            flash(
                "درخواست شروع نردبان از قبل در صف یا در حال پردازش است؛ تا اتمام همان فرآیند درخواست جدید ثبت نمی‌شود.",
                "err",
            )
            return redirect(url_for(".panel"), code=303)

    command_id = _enqueue_command(command_type, payload)
    if command_id:
        flash(f"فرمان {command_type} در صف قرار گرفت (#{command_id}).", "ok")
    else:
        flash("ثبت فرمان ناموفق بود.", "err")
    return redirect(url_for(".panel"), code=303)



# ---------------------------------------------------------------------------
# [relay] رله‌ی پرداخت دیوار: ربات روی سرور دیگری اجرا می‌شود و فقط درخواست‌های
# پرداخت/نردبان را از این سرور (IP ایران) به دیوار/بازارپی می‌فرستد.
# امنیت: هدر X-Relay-Secret باید با divar_relay_secret در configs.json یکی باشد
# (مقایسه‌ی زمان‌ثابت)، فقط میزبان‌های دیوار/بازارپی و فقط https، محدودیت نرخ ساده،
# و هیچ هدر احراز/کوکی لاگ نمی‌شود.
# ---------------------------------------------------------------------------
import base64 as _relay_b64
import hmac as _relay_hmac
import threading as _relay_threading
import time as _relay_time
from urllib.parse import urljoin as _relay_urljoin, urlsplit as _relay_urlsplit

import requests as _relay_requests
from flask import jsonify as _relay_jsonify

_RELAY_ALLOWED_HOSTS = {"api.divar.ir", "divar.ir", "www.divar.ir", "api.bazaar-pay.ir"}
_RELAY_ALLOWED_SUFFIXES = (".divar.ir", ".bazaar-pay.ir")
_RELAY_PLACEHOLDERS = {"", "changeme", "change-me", "secret", "your-secret", "xxx", "placeholder"}
_RELAY_MAX_REQ_BYTES = 512 * 1024
_RELAY_MAX_RESP_BYTES = 8 * 1024 * 1024
_RELAY_RATE_LIMIT = 90  # درخواست در هر ۶۰ ثانیه (برای هر پروسس)
_RELAY_RATE_WINDOW = 60.0
_relay_hits = []
_relay_lock = _relay_threading.Lock()
_RELAY_RESP_HEADERS = ("content-type", "location", "retry-after", "date", "x-request-id")
_RELAY_DROP_REQ_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding"}


def _relay_secret_from_config():
    sec = str(load_config().get("divar_relay_secret") or "").strip()
    if sec.lower() in _RELAY_PLACEHOLDERS or len(sec) < 24:
        return None
    return sec


def _relay_authorized():
    expected = _relay_secret_from_config()
    if not expected:
        return False, ("relay disabled: divar_relay_secret not configured", 503)
    got = str(request.headers.get("X-Relay-Secret") or "")
    if not got or not _relay_hmac.compare_digest(got.encode("utf-8"), expected.encode("utf-8")):
        return False, ("forbidden", 403)
    return True, None


def _relay_rate_ok():
    now = _relay_time.monotonic()
    with _relay_lock:
        while _relay_hits and now - _relay_hits[0] > _RELAY_RATE_WINDOW:
            _relay_hits.pop(0)
        if len(_relay_hits) >= _RELAY_RATE_LIMIT:
            return False
        _relay_hits.append(now)
        return True


def _relay_host_allowed(url):
    try:
        parts = _relay_urlsplit(str(url))
    except Exception:
        return False
    if parts.scheme != "https" or parts.username or parts.password:
        return False
    if parts.port not in (None, 443):
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return host in _RELAY_ALLOWED_HOSTS or host.endswith(_RELAY_ALLOWED_SUFFIXES)


def _relay_safe_url(url):
    """برای لاگ: فقط میزبان و مسیر، بدون query (توکن‌ها در query/مسیر کوتاه می‌شوند)."""
    try:
        p = _relay_urlsplit(str(url))
        segs = []
        for seg in (p.path or "").split("/"):
            segs.append(seg[:4] + "…" if len(seg) > 12 else seg)
        return f"{p.hostname}{'/'.join(segs)}"
    except Exception:
        return "?"


@bp.route("/divar-relay/health", methods=["GET"])
def divar_relay_health():
    ok, err = _relay_authorized()
    if not ok:
        return _relay_jsonify({"ok": False, "error": err[0]}), err[1]
    return _relay_jsonify({"ok": True, "service": "divar-relay"})


@bp.route("/divar-relay", methods=["POST"])
def divar_relay():
    ok, err = _relay_authorized()
    if not ok:
        return _relay_jsonify({"error": err[0]}), err[1]
    if not _relay_rate_ok():
        return _relay_jsonify({"error": "rate limited"}), 429
    if (request.content_length or 0) > _RELAY_MAX_REQ_BYTES:
        return _relay_jsonify({"error": "request too large"}), 413
    env = request.get_json(silent=True)
    if not isinstance(env, dict):
        return _relay_jsonify({"error": "invalid json"}), 400
    method = str(env.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        return _relay_jsonify({"error": "method not allowed"}), 400
    url = str(env.get("url") or "")
    if not _relay_host_allowed(url):
        return _relay_jsonify({"error": "host not allowed"}), 400
    headers = {}
    for k, v in (env.get("headers") or {}).items():
        if str(k).lower() in _RELAY_DROP_REQ_HEADERS:
            continue
        headers[str(k)] = str(v)
    body = None
    if env.get("body_b64"):
        try:
            body = _relay_b64.b64decode(env["body_b64"])
        except Exception:
            return _relay_jsonify({"error": "bad body_b64"}), 400
    elif env.get("json") is not None:
        body = json.dumps(env.get("json"), ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif env.get("data") is not None:
        d = env.get("data")
        body = d.encode("utf-8") if isinstance(d, str) else json.dumps(d).encode("utf-8")
    try:
        timeout = max(3.0, min(float(env.get("timeout") or 30), 60.0))
    except (TypeError, ValueError):
        timeout = 30.0
    follow = bool(env.get("allow_redirects", True))

    started = _relay_time.monotonic()
    current_url, current_method, current_body = url, method, body
    resp = None
    try:
        with _relay_requests.Session() as s:
            for _hop in range(6):
                resp = s.request(
                    current_method, current_url, headers=headers, data=current_body,
                    timeout=timeout, allow_redirects=False, stream=True,
                )
                if not (follow and resp.is_redirect):
                    break
                nxt = _relay_urljoin(current_url, resp.headers.get("Location") or "")
                if not _relay_host_allowed(nxt):
                    break  # تغییر مسیر به میزبان غیرمجاز دنبال نمی‌شود؛ خود پاسخ 30x برمی‌گردد
                resp.close()
                if resp.status_code in (301, 302, 303) and current_method == "POST":
                    current_method, current_body = "GET", None
                current_url = nxt
            content = b""
            for chunk in resp.iter_content(65536):
                content += chunk
                if len(content) > _RELAY_MAX_RESP_BYTES:
                    resp.close()
                    return _relay_jsonify({"error": "upstream response too large"}), 502
    except _relay_requests.exceptions.Timeout as e:
        print(f"[relay] {method} {_relay_safe_url(url)} -> timeout")
        return _relay_jsonify({"error": "upstream_timeout", "detail": str(e)[:200]}), 200
    except _relay_requests.exceptions.RequestException as e:
        print(f"[relay] {method} {_relay_safe_url(url)} -> error {type(e).__name__}")
        return _relay_jsonify({"error": "upstream_error", "detail": str(e)[:200]}), 200

    print(
        f"[relay] {method} {_relay_safe_url(url)} -> {resp.status_code} "
        f"({len(content)}B, {(_relay_time.monotonic() - started):.1f}s)"
    )
    out_headers = {k: resp.headers[k] for k in resp.headers if k.lower() in _RELAY_RESP_HEADERS}
    return _relay_jsonify(
        {
            "status": resp.status_code,
            "reason": resp.reason,
            "headers": out_headers,
            "final_url": current_url,
            "body_b64": _relay_b64.b64encode(content).decode("ascii"),
        }
    )


def create_standalone_app():
    """فقط برای توسعه/اجرای مستقل: python -m probot.web_app"""
    app = Flask(__name__)
    app.secret_key = os.environ.get("PROBOT_WEB_SECRET_KEY") or os.urandom(32)
    app.config["JSON_AS_ASCII"] = False
    app.register_blueprint(bp)

    @app.route("/")
    def _root():
        return redirect(URL_PREFIX + "/", code=302)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    create_standalone_app().run(host="127.0.0.1", port=port, debug=False)
