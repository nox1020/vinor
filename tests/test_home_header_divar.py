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
    chip = re.search(r"#vinorSearchPage \.vn-search-chip \{(.*?)\}", css, re.S).group(1)
    assert "height: 32px;" in chip and "background: transparent;" in chip
    assert "border: 1px solid var(--vn-chip-line);" in chip
    assert "--vn-chip-line: rgba(255,255,255,.12);" in css
    assert "#vinorSearchPage .vn-search-chips::-webkit-scrollbar { display: none;" in css
    assert "scrollbar-width: none;" in css
    assert "--vn-search-chrome: #141416;" in css  # dark palette unchanged
    assert "▾" not in css  # svg carets instead of text glyphs


SCRIPT = ROOT / "app/express_partner/templates/express_partner/partials/search_feed_script.html"


def test_active_chip_is_tinted_outline_not_solid_green():
    css = FEED.read_text(encoding="utf-8")
    active = re.search(r"#vinorSearchPage \.vn-search-chip\.is-active \{(.*?)\}", css, re.S).group(1)
    assert "background: var(--vn-chip-on-bg);" in active
    assert "border-color: var(--vn-chip-on-line);" in active
    assert "color: var(--vn-chip-on-text);" in active
    assert "--vn-chip-on-bg: rgba(16,185,129,.14);" in css
    assert "--vn-search-accent" not in active and "--vn-search-on" not in active
    # long values ellipsize inside a bounded chip
    label = re.search(r"#vinorSearchPage \.vn-search-chip__label \{(.*?)\}", css, re.S).group(1)
    assert "text-overflow: ellipsis;" in label and "max-width: 120px;" in label
    assert "max-width: 190px;" in re.search(r"#vinorSearchPage \.vn-search-chip \{(.*?)\}", css, re.S).group(1)
    # scroll edge-fade only on the side that still has hidden chips
    assert "mask-image: linear-gradient(to left" in css
    assert ".vn-search-chips.has-more-end" in css and ".vn-search-chips.has-more-start" in css


def test_each_chip_has_icon_and_caret_or_clear():
    markup = FEED.read_text(encoding="utf-8")
    for key, flag in (("sort", "sort_on"), ("district", "district_on"), ("price", "price_on"), ("area", "area_on")):
        start = markup.index(f'data-filter-chip="{key}"')
        chip = markup[start:markup.index('data-filter-chip=', start + 20) if key != "area" else markup.index('</div>', markup.index('data-clear-filter="area"'))]
        assert 'class="vn-search-chip__icon"' in chip
        assert f"{{%- if not search_query.{flag} %}}" in chip and 'class="vn-search-chip__caret"' in chip
        assert f'data-clear-filter="{key}"' in chip
    script = SCRIPT.read_text(encoding="utf-8")
    assert "[data-clear-filter]" in script and "e.stopPropagation();" in script
    for case in ("case 'sort': state.sort = 'newest';", "case 'district': state.districts = [];",
                 "case 'price': state.price_min = null; state.price_max = null;",
                 "case 'area': state.area_min = null; state.area_max = null;"):
        assert case in script
    assert "syncStripFade" in script and "{ passive: true }" in script


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


def test_rendered_strip_inactive_vs_active():
    html = _client().get("/express/partner/search").get_data(as_text=True)
    strip = html[html.index("data-filter-strip"):html.index('id="vinorSearchSkeleton"')]
    assert "is-reset" not in strip and "data-clear-filter=" not in strip
    assert strip.count('class="vn-search-chip__caret"') == 4
    assert strip.count('class="vn-search-chip__icon"') == 4

    q = "/express/partner/search?sort=price_asc&price_min=1000000000&district=%D9%88%D9%86%DA%A9"
    html = _client().get(q).get_data(as_text=True)
    strip = html[html.index("data-filter-strip"):html.index('id="vinorSearchSkeleton"')]
    assert strip.count("vn-search-chip is-active") == 3
    for key in ("sort", "district", "price"):
        assert f'data-clear-filter="{key}"' in strip
    assert 'data-clear-filter="area"' not in strip
    assert strip.count('class="vn-search-chip__caret"') == 1  # only the inactive area chip
    reset = re.search(r'<a class="vn-search-chip is-reset"[^>]*>', strip).group(0)
    assert 'data-active-count="3"' in reset and "data-clear-filters" in reset
    assert '<span class="vn-search-chip__badge" aria-hidden="true">۳</span>' in strip
    assert "پاک کردن" in strip
