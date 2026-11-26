# -*- coding: utf-8 -*-
"""هدر خانه به سبک دیوار (وب) — هم‌تراز با fragment_search.xml اپ."""
from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "app/express_partner/templates/express_partner/partials/search_feed.html"


def _head(markup: str) -> str:
    start = markup.index('<div class="vn-search-head" data-vn-home-header>')
    return markup[start:markup.index('<div class="vn-search-chips"', start)]


def test_unified_search_pill_contains_divider_and_city():
    head = _head(FEED.read_text(encoding="utf-8"))
    field_at = head.index('class="vn-search-field"')
    order = [head.index(x) for x in (
        'id="vinorSearchInput"', 'id="vinorSearchClear"', 'class="vn-search-divider"', 'id="searchCityTrigger"',
    )]
    assert field_at < order[0] and order == sorted(order)
    # city chip sits inside the same pill (closes before the bell)
    pill = head[field_at:head.index("{% if session.get('user_phone') %}")]
    assert 'id="searchCityTrigger"' in pill and 'id="searchCityLabel"' in pill
    assert 'data-city-picker-open="searchCityPicker"' in pill


def test_pill_and_chip_styles_divar_like():
    css = FEED.read_text(encoding="utf-8")
    field = re.search(r"#vinorSearchPage \.vn-search-field \{(.*?)\}", css, re.S).group(1)
    assert "border-radius: 999px;" in field and "height: 44px;" in field
    city = re.search(r"#vinorSearchPage \.vn-search-city \{(.*?)\}", css, re.S).group(1)
    assert "background: transparent;" in city and "border: 0;" in city  # no pill-in-box
    face = re.search(r"#vinorSearchPage \.vn-search-chip__face \{(.*?)\}", css, re.S).group(1)
    assert "height: 32px;" in face and "background: transparent;" in face
    assert "#vinorSearchPage .vn-search-chips::-webkit-scrollbar { display: none;" in css
    assert "scrollbar-width: none;" in css
    assert "--vn-search-chrome: #141416;" in css  # dark palette unchanged
    assert "▾" not in css  # svg carets instead of text glyphs


def test_all_filters_and_actions_still_present():
    markup = FEED.read_text(encoding="utf-8")
    for sheet in ("sort", "district", "price", "area"):
        assert f'data-open-sheet="{sheet}"' in markup
    assert "data-clear-filters" in markup
    assert "بازنشر" not in markup


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


def test_bell_only_for_signed_in_users():
    guest = _client().get("/express/partner/search")
    assert guest.status_code == 200
    html = guest.get_data(as_text=True)
    assert "data-vn-home-header" in html
    assert "data-home-bell" not in html

    phone = "09121111111"
    with mock.patch("app.express_partner.partner_roles.partner_is_approved", return_value=True), \
         mock.patch("app.utils.storage.load_express_partners", return_value=[{"phone": phone, "status": "approved"}]):
        resp = _client(phone).get("/express/partner/search")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    bell = re.search(r'<a class="vn-search-bell"[^>]*>', html).group(0)
    assert 'href="/express/partner/notifications"' in bell
    assert 'aria-label="اعلان‌ها"' in bell
