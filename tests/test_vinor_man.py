# -*- coding: utf-8 -*-
"""Locks for the Vinor Man tab (phase A). One test, same fixtures as consultant locks."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

PHONE = "09124000071"
MASK = "۰۹۱۲•••۰۰۷۱"
RAW_FA = "۰۹۱۲۴۰۰۰۰۷۱"
PROFILE = "/express/partner/profile"
PALETTE = {
    "#000000",
    "#1C1C1E",
    "#2F2F2F",
    "#ECECEC",
    "#8E8E93",
    "#14FFFFFF",
    "#29FFFFFF",
    "#E22828",
    "#C91F1F",
    "#FFFFFF",
    "#10B981",
    "#FB7185",
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-consultant-locks")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.delenv("VINOR_CONSULTANT_DRY_RUN", raising=False)
    monkeypatch.delenv("VINOR_CONSULTANT_SIMULATE", raising=False)
    monkeypatch.delenv("VINOR_CONSULTANT_API_ENABLED", raising=False)

    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, phone: str = PHONE) -> None:
    with client.session_transaction() as sess:
        sess["user_phone"] = phone
        sess.pop("logged_in", None)
        sess.pop("admin_phone", None)


def _chunk(html: str) -> str:
    start = html.find('id="vinorMePage"')
    assert start != -1
    main = html.rfind("<main", 0, start)
    end = html.find("</main>", start)
    assert main != -1 and end != -1
    return html[main:end]


def _internal_hrefs(chunk: str) -> list[str]:
    found = []
    for href in re.findall(r'href="([^"]*)"', chunk):
        path = urlsplit(href).path or ""
        if path.startswith("/logout") or path.startswith("/api/logout"):
            continue
        if href.startswith("/") and not href.startswith("//"):
            found.append(href)
    return found


def _assert_next_safe(href: str) -> None:
    for val in parse_qs(urlsplit(href).query).get("next", []):
        decoded = unquote(val)
        assert decoded.startswith("/"), decoded
        assert not decoded.startswith("//"), decoded
        assert not decoded.startswith("/\\"), decoded


def _crawl(client, html: str) -> None:
    for href in _internal_hrefs(_chunk(html)):
        _assert_next_safe(href)
        resp = client.get(href, follow_redirects=True)
        assert resp.status_code < 400, (href, resp.status_code)


def _style_hexes(html: str) -> set[str]:
    found = set()
    for block in re.findall(r"<style\b[^>]*>(.*?)</style>", html, flags=re.I | re.S):
        if "#vinorMePage" not in block:
            continue
        for item in re.findall(r"#[0-9a-fA-F]{3,8}\b", block):
            found.add(item.upper())
    return found


def test_vinor_man_menu_locks(client, monkeypatch):
    guest = client.get(PROFILE)
    assert guest.status_code == 200
    guest_cc = guest.headers.get("Cache-Control") or ""
    assert "no-store" in guest_cc
    guest_body = guest.get_data(as_text=True)
    guest_page = _chunk(guest_body)
    assert "وینور من" in guest_body
    assert "ورود به حساب" in guest_body
    assert "next=%2Fexpress%2Fpartner%2Fprofile" in guest_body
    assert "خروج" not in guest_page
    assert "تنظیمات" not in guest_page or "تنظیمات و پشتیبانی" in guest_page
    assert 'href="/express/partner/settings"' not in guest_page
    assert "کیف پول" not in guest_page
    assert "vn-me-badge" not in guest_page
    assert "vn-me-profile" not in guest_page
    assert "همکار وینور" not in guest_page
    _crawl(client, guest_body)

    _login(client)
    logged = client.get(PROFILE)
    assert logged.status_code == 200
    logged_cc = logged.headers.get("Cache-Control") or ""
    assert "private" in logged_cc
    assert "no-store" in logged_cc
    body = logged.get_data(as_text=True)
    assert MASK in body
    assert PHONE not in body
    assert RAW_FA not in body
    assert "آگهی‌های من" in body
    assert "نشان‌شده‌ها" in body
    assert "data-vinor-logout" in body
    assert 'role="dialog"' in body
    assert "خروج از حساب؟" in body
    assert "انصراف" in body
    assert 'href="/express/partner/consultant"' in body
    _crawl(client, body)
    assert _style_hexes(body) <= PALETTE
    page = _chunk(body)
    assert "#2563eb" not in page.lower()
    assert "#4ade80" not in page.lower()
    # A section heading must not look like a second copy of an action.
    row_labels = re.findall(r'class="vn-me-row__title[^"]*">([^<]+)', page)
    group_labels = re.findall(r'class="vn-me-label">([^<]+)', page)
    assert len(row_labels) == len(set(row_labels))
    assert set(row_labels).isdisjoint(group_labels)
    for block in re.findall(r"<style\b[^>]*>(.*?)</style>", body, flags=re.I | re.S):
        if ".vn-divar-tab" not in block:
            continue
        low = block.lower()
        assert "#2563eb" not in low
        assert "#4ade80" not in low

    monkeypatch.setenv("VINOR_CONSULTANT_API_ENABLED", "0")
    off = client.get(PROFILE)
    off_body = off.get_data(as_text=True)
    assert off.status_code == 200
    assert "درخواست همکاری" in off_body
    assert not re.search(r'class="vn-me-label">آگهی‌های من<', off_body)
    assert "همکاری با وینور" in off_body
    assert 'href="/express/partner/apply"' in off_body
    assert 'href="/express/partner/consultant"' not in off_body
    _crawl(client, off_body)


MARKETER_LABEL = "می‌خواهم بازاریاب وینور شوم"
HOME = "/express/partner/home"


def test_vinor_man_news_page_and_shortcut_are_removed(client):
    """The retired news page has no URL or Vinor Man shortcut."""
    assert client.get("/express/partner/news").status_code == 404
    _login(client)
    profile_html = client.get(PROFILE).get_data(as_text=True)
    assert 'href="/express/partner/news"' not in profile_html


def test_home_is_the_app_listing_feed_for_every_role(client, app):
    """خانهٔ وب = خانهٔ اپ: فقط جستجو، فیلترها و فهرست آگهی‌ها. کاشی‌ها و ابزار حساب در «وینور من»."""
    def assert_feed(html: str) -> None:
        assert 'id="vinorSearchPage"' in html
        assert 'placeholder="جستجو در همه آگهی‌ها"' in html
        assert "همه استان‌ها" in html
        for label in ("جدیدترین", "محله", "قیمت", "متراژ"):
            assert label in html
        assert 'class="vn-hub__tiles"' not in html
        assert 'class="vn-hub__hero"' not in html
        assert re.findall(r'class="vn-divar-tab__label">([^<]+)', html) == [
            "خانه", "پیگیری", "افزودن", "مشتریان", "وینور من",
        ]

    assert_feed(client.get(HOME).get_data(as_text=True))
    _login(client)
    with app.app_context():
        from app.utils.storage import save_express_partners

        save_express_partners([
            {"phone": PHONE, "name": "همکار", "status": "approved"},
        ])
    assert_feed(client.get(HOME).get_data(as_text=True))


def test_marketer_banner_moves_to_vinor_man(client, app):
    """بنر خانه حذف شده و همان مسیر از وینور من باز می‌شود."""
    guest_home = client.get(HOME).get_data(as_text=True)
    assert client.get(HOME).status_code == 200
    assert MARKETER_LABEL not in guest_home
    assert 'class="vn-hub__hero"' not in guest_home

    guest_me = client.get(PROFILE).get_data(as_text=True)
    assert MARKETER_LABEL in guest_me
    assert "login_next=/express/partner/consultant" in guest_me
    assert "menu=1" in guest_me
    assert "شروع همکاری فروش و دریافت پورسانت" in guest_me

    _login(client)
    open_home = client.get(HOME)
    assert open_home.status_code == 200
    open_home_body = open_home.get_data(as_text=True)
    assert MARKETER_LABEL not in open_home_body
    assert 'class="vn-hub__hero"' not in open_home_body
    open_me = client.get(PROFILE).get_data(as_text=True)
    assert MARKETER_LABEL in open_me
    assert 'href="/express/partner/consultant"' in open_me

    with app.app_context():
        from app.utils.storage import save_express_partner_apps

        save_express_partner_apps([
            {"phone": PHONE, "status": "pending", "name": "متقاضی"},
        ])
    pending_home = client.get(HOME).get_data(as_text=True)
    assert MARKETER_LABEL not in pending_home
    assert 'id="vinorSearchPage"' in pending_home
    pending_me = client.get(PROFILE).get_data(as_text=True)
    assert MARKETER_LABEL not in pending_me
    assert "وضعیت درخواست" in pending_me
    assert 'href="/express/partner/consultant"' in pending_me

    with app.app_context():
        from app.utils.storage import save_express_partners

        save_express_partners([
            {"phone": PHONE, "name": "همکار", "status": "approved"},
        ])
    approved_home = client.get(HOME).get_data(as_text=True)
    assert MARKETER_LABEL not in approved_home
    assert 'id="vinorSearchPage"' in approved_home
    approved_me = client.get(PROFILE).get_data(as_text=True)
    assert MARKETER_LABEL not in approved_me
    assert "وضعیت درخواست" not in _chunk(approved_me)
    assert 'href="/express/partner/consultant"' not in approved_me


@pytest.mark.parametrize(
    ("path", "title"),
    [
        ("/express/partner/customers", "مشتریان"),
        ("/express/partner/requests", "پیگیری"),
    ],
)
def test_guest_private_tabs_open_the_single_login_page(client, path, title):
    response = client.get(path, follow_redirects=False)
    assert response.status_code in (302, 303)
    loc = response.headers["Location"]
    assert "/express/partner/login" in loc and ("next=" + path in loc or "next=" + path.replace("/", "%2F") in loc)


@pytest.mark.parametrize("error, created_at, phone, expected_success", [
    ("OTP_COOLDOWN", "recent", "09120000001", True),
    ("OTP_COOLDOWN", "expired", "09120000001", False),
    ("OTP_COOLDOWN", "recent", "09120000002", False),
    ("OTP_RATE_LIMITED", "recent", "09120000001", False),
])
def test_partner_otp_cooldown_reuses_only_matching_live_challenge(
    client, monkeypatch, error, created_at, phone, expected_success,
):
    import time
    from app.express_partner import routes

    with client.session_transaction() as session:
        session["otp_code"] = routes.OTP_SESSION_PENDING
        session["otp_phone"] = "09120000001"
        session["otp_created_at"] = time.time() if created_at == "recent" else 1
    monkeypatch.setattr(
        routes, "_issue_partner_login_otp",
        lambda _phone: (False, error, 40),
    )
    response = client.post(
        "/express/partner/api/login-request",
        json={"phone": phone, "accept_legal": True},
    )
    assert response.get_json()["success"] is expected_success
    assert response.status_code == (200 if expected_success else 429)
    if expected_success:
        assert response.get_json()["otp_pending"] is True
        assert "قبلی" in response.get_json()["message"]


def test_web_inline_otp_has_safe_retry_and_autofill_controls(client):
    from pathlib import Path

    otp = Path("app/express_partner/templates/express_partner/auth/login_step2.html").read_text(encoding="utf-8")
    assert 'id="resendBtn"' in otp
    assert "vinorFillOtpFromApp" in otp
    assert 'autocomplete="one-time-code"' in otp