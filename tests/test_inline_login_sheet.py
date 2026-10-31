# -*- coding: utf-8 -*-
"""Login is ONE in-app page (no modal/sheet, no iframe), with app-style back arrow."""
from __future__ import annotations

from pathlib import Path

ROOT = Path("app")


def test_no_login_sheet_or_iframe_left():
    assert not (ROOT / "static/express-partner/login-sheet.js").exists()
    assert not (ROOT / "express_partner/templates/express_partner/guest_tab_login.html").exists()
    base = (ROOT / "express_partner/templates/express_partner/base.html").read_text(encoding="utf-8")
    assert "login-sheet" not in base


def test_login_page_has_app_back_arrow_that_returns():
    html = (ROOT / "express_partner/templates/express_partner/auth/login_step1.html").read_text(encoding="utf-8")
    assert 'id="loginStep1Back"' in html and "fa-arrow-right" in html and "fa-xmark" not in html.split("</header>")[0]
    assert "__vinorExpressLastHref" in html and "back.setAttribute('href'" in html
