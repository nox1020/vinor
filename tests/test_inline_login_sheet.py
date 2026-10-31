# -*- coding: utf-8 -*-
"""Inline login: every login entry opens the same phone→OTP sheet on the current page."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path("app")
JS = (ROOT / "static/express-partner/login-sheet.js").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k, v in {
        "INSTANCE_PATH": str(tmp_path), "SECRET_KEY": "unit-inline-login", "SESSION_COOKIE_SECURE": "0",
        "VINOR_DISABLE_SMS_SCHEDULER": "1", "VINOR_DISABLE_REACH": "1", "VINOR_OPTIMIZATION_SCHEDULER": "0",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'v.db'}",
    }.items():
        monkeypatch.setenv(k, v)
    from app import create_app

    a = create_app()
    a.config.update(TESTING=True)
    return a.test_client()


def test_auth_state_endpoint(client):
    r = client.get("/express/partner/api/auth-state")
    assert r.get_json() == {"logged_in": False}
    assert "no-store" in r.headers["Cache-Control"]
    with client.session_transaction() as s:
        s["user_phone"] = "09124000071"
    assert client.get("/express/partner/api/auth-state").get_json() == {"logged_in": True}


def test_every_page_loads_the_sheet(client):
    html = client.get("/express/partner/home").get_data(as_text=True)
    assert "express-partner/login-sheet.js" in html


def test_login_url_still_works_as_fallback(client):
    assert client.get("/express/partner/login").status_code == 200


def test_sheet_intercepts_links_and_navigation_and_stays_on_page():
    assert "window.vinorOpenLoginSheet = open" in JS
    assert "window.vinorExpressNavigate = wrapped" in JS
    assert "window.location.reload()" in JS  # no next → stay on the same page
    assert "vinor-login-leave" in JS and "/express/partner/api/auth-state" in JS
    assert 'allow="otp-credentials"' in JS


def test_js_login_redirects_go_through_sheet():
    for rel in ("static/express-partner/express-nav.js", "static/express-partner/ai-chat.js"):
        assert "vinorGoLogin" in (ROOT / rel).read_text(encoding="utf-8"), rel
    assert "vinorOpenLoginSheet" in (ROOT / "static/express-partner/land-detail.js").read_text(encoding="utf-8")
    nav = (ROOT / "express_partner/templates/express_partner/partials/bottom_nav.html").read_text(encoding="utf-8")
    assert "vinorGoLogin" in nav
    tab = (ROOT / "express_partner/templates/express_partner/guest_tab_login.html").read_text(encoding="utf-8")
    assert "vinor-login-leave" in tab
