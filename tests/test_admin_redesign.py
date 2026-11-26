# -*- coding: utf-8 -*-
"""Admin panel redesign: auth guards, page smoke, CSRF, nav structure, XSS."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "admin" / "templates" / "admin"
NOW = datetime.now(timezone.utc)
P1, P2, U1 = "09121234567", "09129876543", "09124445566"
EVIL = "علی');alert(1);//"

PRIMARY = [
    "/admin/",
    "/admin/listings/properties",
    "/admin/listings/properties?status=pending",
    "/admin/express",
    "/admin/express/visit-requests",
    "/admin/express/visit-requests?filter=actions",
    "/admin/financial/withdrawals",
    "/admin/financial/withdrawals?filter=all",
    "/admin/express/partners",
    "/admin/express/partners?filter=pending",
    "/admin/express/partners?filter=users",
]
SECONDARY = [
    "/admin/reports",
    "/admin/lands",
    "/admin/pending-lands",
    "/admin/approved-lands",
    "/admin/rejected-lands",
    "/admin/add-land",
    "/admin/settings",
    "/admin/home-ads",
    "/admin/express/cities",
    "/admin/express/commissions",
    "/admin/express/deals/overdue",
    "/admin/express/deals/missing-pending",
    "/admin/top-sellers",
    "/admin/sms-notifications",
    f"/admin/express/partners/{P1}",
]


def _iso(**kw):
    return (NOW - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-admin-redesign")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True)
    with application.app_context():
        from app.utils import storage as S

        S.save_express_partners([
            {"phone": P1, "name": "مسعود حسینی", "status": "approved", "partner_tier": "special",
             "plus_expires_at": (NOW + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"), "city": "تهران"},
            {"phone": P2, "name": EVIL, "status": "approved", "city": "کرج"},
        ])
        S.save_express_partner_apps([
            {"id": 1, "phone": "09191230000", "name": EVIL, "city": "تهران", "status": "pending", "created_at": _iso(hours=3)},
        ])
        S.save_users([{"phone": U1, "name": "کاوه", "created_at": _iso(days=2)}])
        S.save_ads([
            {"code": "1302", "title": EVIL, "owner": U1, "status": "pending", "owner_home": True,
             "source": "my_property", "created_at": _iso(hours=1), "price_total": 1_000_000_000, "size": 90,
             "city": "تهران", "images": []},
            {"code": "1290", "title": "ویلا", "owner": P1, "status": "approved", "is_express": True,
             "express_status": "approved", "created_at": _iso(days=2), "images": []},
        ])
        S.save_partner_withdrawals([
            {"id": "w1", "phone": P1, "amount": 40_000_000, "bank_name": "بانک ملت", "holder_name": "مسعود حسینی",
             "sheba": "IR820540102680020817909002", "status": "pending", "created_at": _iso(hours=2)},
        ])
        S.save_reports([{"id": 1, "code": "1290", "reason": "قیمت غیرواقعی", "status": "open", "created_at": _iso(hours=4)}])
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"


def _body(resp):
    return resp.get_data(as_text=True)


def _plain_admin_get_rules(app):
    out = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/admin") or rule.arguments or "GET" not in (rule.methods or ()):
            continue
        if rule.endpoint in {"admin.login", "admin.logout"}:
            continue
        out.append(rule.rule)
    return sorted(set(out))


# ── Auth guards ──────────────────────────────────────────────────────────


# PWA assets the browser fetches before login; they carry no admin data.
PUBLIC_ASSETS = {"/admin/manifest.webmanifest", "/admin/sw.js"}


def test_every_admin_get_route_requires_login(app, client):
    leaks = []
    for path in [p for p in _plain_admin_get_rules(app) if p not in PUBLIC_ASSETS] + ["/admin/sms-campaign/job/abc", f"/admin/express/partners/{P1}"]:
        seen = 0
        cur = path
        while True:
            r = client.get(cur)
            if r.status_code in (401, 403):
                break
            if r.status_code not in (301, 302, 303, 307, 308):
                leaks.append((path, r.status_code))
                break
            loc = urlparse(r.headers.get("Location", "")).path
            if loc.startswith("/admin/login"):
                break
            if not loc.startswith("/admin") or seen > 4:
                leaks.append((path, loc))
                break
            cur, seen = loc, seen + 1
    assert not leaks, leaks


def test_sms_phonebook_post_requires_login(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    r = client.post("/admin/sms-campaign/phonebook", data={"name": "x", "numbers": "09120000000"})
    assert r.status_code in (302, 401, 403)
    assert "/admin/login" in r.headers.get("Location", "/admin/login")


def test_admin_post_without_csrf_is_rejected(app, client):
    _login(client)
    r = client.post("/admin/reports/1/resolve")
    assert r.status_code in (302, 400, 403)
    with app.app_context():
        from app.utils.storage import load_reports

        assert load_reports()[0]["status"] == "open"


# ── Pages render ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", PRIMARY + SECONDARY)
def test_admin_pages_render(client, path):
    _login(client)
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code)
    body = _body(r)
    assert 'class="ad-sidebar' in body
    assert "admin/vinor-control.css" in body
    assert "\u0628\u0627\u0632\u0646\u0634\u0631" not in body  # the retired repost label


def test_every_plain_admin_get_route_has_no_server_error(app, client):
    _login(client)
    bad = [(p, client.get(p).status_code) for p in _plain_admin_get_rules(app)]
    bad = [(p, s) for p, s in bad if s >= 500]
    assert not bad, bad


def test_bad_paging_args_do_not_500(client):
    _login(client)
    for path in ("/admin/lands?page=abc", "/admin/reports?page=x&per_page=y", "/admin/pending-lands?page=-4"):
        assert client.get(path).status_code == 200, path


def test_reports_page_links_to_listing(client):
    _login(client)
    body = _body(client.get("/admin/reports"))
    assert "/express/1290" in body
    assert 'name="csrf_token"' in body


def test_login_page_is_persian_and_has_csrf(client, monkeypatch):
    monkeypatch.setattr("admin.routes.send_sms_code", lambda *a, **k: None, raising=False)
    r = client.get("/admin/login")
    body = _body(r)
    assert r.status_code == 200
    assert 'lang="fa" dir="rtl"' in body
    assert 'name="csrf_token"' in body and 'name="otp_code"' in body
    assert 'value="verify"' in body and 'value="send"' in body
    assert "vc-lang-switch" in body


# ── Shell & nav ──────────────────────────────────────────────────────────


def test_nav_has_six_sections_and_badges(client):
    _login(client)
    body = _body(client.get("/admin/"))
    for label in ("داشبورد", "آگهی‌ها / فایل‌ها", "بازدیدها و پیگیری", "مالی و برداشت‌ها",
                  "کاربران و همکاران", "تنظیمات و ابزارها"):
        assert label in body
    assert len(re.findall(r'class="ad-nav-item (?:is-active)?\s*"', body)) == 6
    assert "ad-count" in body
    for keep in ("adminOpsDashPage", "vinorControlShell", "⌘K", "vc-lang-switch", "vinor-i18n.js"):
        assert keep in body


def test_nav_and_command_links_resolve(app, client):
    from admin.nav import build_nav, command_items

    with app.test_request_context("/admin/"):
        sections = build_nav("admin.dashboard", {})
        groups = command_items(sections)
    assert [s["key"] for s in sections] == ["dashboard", "listings", "visits", "finance", "people", "tools"]
    urls = {s["url"] for s in sections}
    urls |= {c["url"] for s in sections for c in s["children"]}
    urls |= {i["href"] for g in groups for i in g["items"]}
    _login(client)
    broken = []
    for url in sorted(urls):
        r = client.get(url)
        if r.status_code not in (200, 302):
            broken.append((url, r.status_code))
    assert not broken, broken


def test_dashboard_hides_finance_without_permission(client, monkeypatch):
    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: False)
    _login(client)
    body = _body(client.get("/admin/"))
    assert "دسترسی مالی ندارید" in body
    assert "IR820540102680020817909002" not in body


# ── Security in markup ───────────────────────────────────────────────────

_FORM_RE = re.compile(r"<form\b[^>]*>.*?</form>", re.S | re.I)


def test_post_forms_in_admin_templates_carry_csrf():
    missing = []
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for m in _FORM_RE.finditer(text):
            form = m.group(0)
            head = form[: form.find(">") + 1]
            if not re.search(r"method\s*=\s*[\"']post[\"']", head, re.I):
                continue
            if "csrf_token" not in form and "csrf_field" not in form:
                missing.append(f"{path.relative_to(TEMPLATES)}:{text[: m.start()].count(chr(10)) + 1}")
    assert not missing, missing


def test_no_user_data_in_inline_js_handlers():
    risky = re.compile(r"""(on(click|submit|change)|@click[.\w]*|x-on:\w+)\s*=\s*"[^"]*\{\{(?!\s*(?:loop\.index|csrf))[^"]*\}\}""")
    hits = []
    for path in TEMPLATES.rglob("*.html"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if risky.search(line):
                hits.append(f"{path.relative_to(TEMPLATES)}:{i}")
    assert not hits, hits


def test_hostile_names_are_escaped_not_scripted(client):
    _login(client)
    for path in ("/admin/express/partners", "/admin/listings/properties?status=pending", "/admin/pending-lands"):
        body = _body(client.get(path))
        assert "alert(1)" in body, path
        assert "');alert(1)" not in body, path


# ── Filters ──────────────────────────────────────────────────────────────


def test_ui_filters():
    from admin.ui_filters import admin_dt, fa_num

    assert fa_num(12500) == "۱۲٬۵۰۰"
    assert fa_num("x") in ("۰", "x")
    assert admin_dt("not a date") == "—"
    out = admin_dt("2026-11-26T13:47:11Z")
    assert "T" not in out and "Z" not in out
    assert "۱۴۰۵" in out
