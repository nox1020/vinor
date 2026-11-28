# -*- coding: utf-8 -*-
"""زیرصفحات «وینور من» با برگشت به پروفایل؛ برچسب «ویرایش» از ردیف هویت حذف شده است."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

import pytest

PHONE = "09121234567"
PROFILE = "/express/partner/profile"

# صفحه → مسیر. از پروفایل با ?from=profile باز می‌شوند.
SUBPAGES = [
    "/express/partner/profile/edit",
    "/express/partner/notifications",
    "/express/partner/training",
    "/express/partner/customers",
    "/express/partner/requests",
    "/express/partner/invite",
    "/express/partner/commissions",
    "/express/partner/wallet",
    "/express/partner/settings",  # already always back to profile
    "/express/partner/legal/terms",
    "/express/partner/my-property",
    "/express/partner/favorites",
]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-profile-subpage-back")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_PLUS_SYSTEM_ENABLED", "1")
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with application.app_context():
        from app.utils import storage as S
        S.save_express_partners([
            {"phone": PHONE, "name": "مسعود حسینی", "status": "approved", "city": "تهران",
             "partner_tier": "special"},
        ])
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, phone=PHONE):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone


def _back_hrefs(html: str) -> list[str]:
    found = []
    for m in re.finditer(r'<a\b[^>]*>', html, flags=re.I):
        tag = m.group(0)
        if "بازگشت" not in tag and 'data-vinor-express-nav="back"' not in tag and "vp-back" not in tag and "ep-from-profile-back" not in tag:
            if 'aria-label="بازگشت"' not in tag and "aria-label='بازگشت'" not in tag:
                continue
        href = re.search(r'href="([^"]*)"', tag)
        if href:
            found.append(href.group(1))
    return found


def test_identity_row_has_no_edit_label(client):
    _login(client)
    html = client.get(PROFILE).get_data(as_text=True)
    open_at = html.index('class="vn-me-profile"')
    tag_start = html.rfind("<a", 0, open_at)
    inner_start = html.index(">", open_at) + 1
    end = html.index("</a>", inner_start)
    inner = html[inner_start:end]
    assert "vn-me-profile__edit" in inner
    assert "vn-me-chev" in inner
    assert "ویرایش" not in inner
    assert 'aria-label="ویرایش پروفایل' in html[tag_start:inner_start]
    # خودِ هدر «وینور من» همچنان به خانه برمی‌گردد.
    header = html[html.index('id="partnerProfileHeader"'): html.index("</header>", html.index('id="partnerProfileHeader"'))]
    assert 'href="/express/partner/home"' in header


def test_profile_links_carry_from_profile(client):
    _login(client)
    html = client.get(PROFILE).get_data(as_text=True)
    start = html.index('id="vinorMePage"')
    page = html[start:html.index("</main>", start)]
    hrefs = re.findall(r'href="([^"]+)"', page)
    stamped = [h for h in hrefs if "from=profile" in h]
    # هویت، آگهی‌ها، نشان‌شده‌ها، اعلان، پیگیری، کیف پول، آموزش، تنظیمات، پشتیبانی، قوانین، …
    assert len(stamped) >= 8
    for path in ("/express/partner/profile/edit", "/express/partner/notifications",
                 "/express/partner/requests", "/express/partner/commissions",
                 "/express/partner/settings", "/express/partner/legal/terms"):
        assert any(path in h and "from=profile" in h for h in hrefs), path


@pytest.mark.parametrize("path", SUBPAGES)
def test_subpage_back_goes_to_profile_when_opened_from_profile(client, path):
    _login(client)
    sep = "&" if "?" in path else "?"
    resp = client.get(path + sep + "from=profile", follow_redirects=True)
    assert resp.status_code == 200, (path, resp.status_code)
    html = resp.get_data(as_text=True)
    backs = _back_hrefs(html)
    assert backs, path
    assert any(urlsplit(h).path.rstrip("/") == "/express/partner/profile" for h in backs), (path, backs)


@pytest.mark.parametrize("path", [
    "/express/partner/notifications",
    "/express/partner/training",
    "/express/partner/requests",
    "/express/partner/customers",
    "/express/partner/invite",
    "/express/partner/commissions",
])
def test_subpage_back_stays_home_when_not_from_profile(client, path):
    _login(client)
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    backs = _back_hrefs(html)
    assert backs, path
    assert any(urlsplit(h).path.rstrip("/") in {"/express/partner/home", "/express/partner"} for h in backs), (path, backs)
    assert not any(urlsplit(h).path.rstrip("/") == "/express/partner/profile" for h in backs), (path, backs)


def test_wallet_nested_steps_keep_origin(client):
    _login(client)
    wallet = client.get("/express/partner/wallet?from=profile").get_data(as_text=True)
    assert 'href="/express/partner/profile"' in wallet
    assert "from=profile" in wallet
    # شارژ و برداشت یک پله به کیف پول برمی‌گردند و مبدأ را نگه می‌دارند.
    withdraw = client.get("/express/partner/wallet/withdraw?from=profile").get_data(as_text=True)
    assert "/express/partner/wallet" in withdraw
    assert "from=profile" in withdraw
    assert re.search(r'data-href="[^"]*from=profile', withdraw)


def test_help_redirect_carries_origin(client):
    _login(client)
    resp = client.get("/express/partner/help?from=profile", follow_redirects=False)
    assert resp.status_code in (301, 302)
    loc = resp.headers.get("Location", "")
    assert "ai=1" in loc
    assert "from=profile" in loc
    home = client.get(loc, follow_redirects=True).get_data(as_text=True)
    assert "ep-from-profile-back" in home
    assert 'href="/express/partner/profile"' in home


def test_nav_origin_helpers():
    from app.express_partner.nav_origin import with_from

    assert with_from("/express/partner/requests") == "/express/partner/requests?from=profile"
    stamped = with_from("/express/partner/login?next=/express/partner/favorites")
    assert "next=" in stamped and "from%3Dprofile" in stamped
    assert stamped.startswith("/express/partner/login?")
    assert with_from("/x", origin="nope") == "/x"


def test_plus_template_back_uses_origin():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    plus = (root / "app/express_partner/templates/express_partner/plus.html").read_text(encoding="utf-8")
    assert "subpage_back_url()" in plus
    assert "vp-back" in plus
    profile = (root / "app/express_partner/templates/express_partner/profile.html").read_text(encoding="utf-8")
    assert "express_partner.plus" in profile
