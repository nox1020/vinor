# -*- coding: utf-8 -*-
"""هدر «وینور من» هم‌ساختار «مشتریان» و «پیگیری» (ep_header_start + ep_header_row)."""
from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "app/express_partner/templates/express_partner"


def _header_call(name: str) -> tuple[str, str]:
    src = (TPL / name).read_text(encoding="utf-8")
    start = re.search(r"\{\{ ep_header_start\(([^)]*)\) \}\}", src)
    row = re.search(r"\{% call ep_header_row\('([^']+)', ([^,]+), inner_class='([^']+)'\) %\}", src)
    assert start and row, name
    return start.group(1), row.group(2) + "|" + row.group(3)


def test_profile_uses_same_header_macros_as_customers_and_requests():
    profile = (TPL / "profile.html").read_text(encoding="utf-8")
    assert "import ep_header_start, ep_header_end, ep_header_row" in profile
    p_start, p_row = _header_call("profile.html")
    c_start, c_row = _header_call("customers.html")
    r_start, r_row = _header_call("requests.html")
    assert p_start == "id='partnerProfileHeader'"
    # same back target (Home) + same inner width as both references
    assert p_row == c_row == r_row == "url_for('express_partner.home')|max-w-lg mx-auto w-full"
    assert "{% call ep_header_row('وینور من'" in profile
    assert "{{ ep_header_end() }}" in profile
    # header renders before the page body, like customers.html
    assert profile.index("ep_header_start(") < profile.index('<main id="vinorMePage"')
    # old bespoke title bar is gone
    assert "vn-me-header" not in profile
    assert "vn-me-header" not in (TPL / "partials/profile_page_styles.html").read_text(encoding="utf-8")


def _client(phone=None):
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    if phone:
        with client.session_transaction() as sess:
            sess["user_phone"] = phone
            sess["logged_in"] = True
            sess["VINOR_IS_EXPRESS_PARTNER"] = True
    return client


def _rendered_header(html: str, hid: str) -> str:
    start = html.index(f'<header id="{hid}"')
    return html[start:html.index("</header>", start)]


def _shape(header: str) -> str:
    """Header markup with the title/id/hrefs neutralised, to compare structure."""
    header = re.sub(r'id="partner\w+Header"', 'id="X"', header)
    header = re.sub(r'<h1 class="ep-partner-header-title">[^<]*</h1>', "<h1/>", header)
    return re.sub(r"\s+", " ", header).strip()


def test_rendered_profile_header_matches_customers_structure():
    for phone in (None, "09121111111"):
        with mock.patch("app.express_partner.partner_roles.partner_is_approved", return_value=True), \
             mock.patch("app.utils.storage.load_express_partners", return_value=[{"phone": "09121111111", "status": "approved"}]):
            resp = _client(phone).get("/express/partner/profile")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        head = _rendered_header(html, "partnerProfileHeader")
        assert 'class="ep-partner-header ep-partner-header--shell-none' in head
        assert '<h1 class="ep-partner-header-title">وینور من</h1>' in head
        assert 'href="/express/partner/home"' in head and 'data-vinor-express-nav="back"' in head
        assert "ep-header-title-pill" in head and "h-[42px]" in head
        assert 'id="vinorMePage" class="partner-page-scroll-pad"' in html

    customers = (TPL / "customers.html").read_text(encoding="utf-8")
    from app import create_app
    app = create_app()
    with app.test_request_context("/"):
        from flask import render_template_string
        macro = "{% from 'express_partner/partials/partner_header.html' import ep_header_start, ep_header_end, ep_header_row %}"
        c = render_template_string(macro + customers[customers.index("{{ ep_header_start"):customers.index("{{ ep_header_end() }}") + len("{{ ep_header_end() }}")])
        profile = (TPL / "profile.html").read_text(encoding="utf-8")
        p = render_template_string(macro + profile[profile.index("{{ ep_header_start"):profile.index("{{ ep_header_end() }}") + len("{{ ep_header_end() }}")])
    assert _shape(p) == _shape(c)
