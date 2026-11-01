# -*- coding: utf-8 -*-
"""Web home rows use the APK card rules and the feed's hidden states stay hidden."""
from __future__ import annotations

from pathlib import Path

from app.express_partner.listing_card import card_area, card_fields, card_place, card_price

FEED = Path(__file__).resolve().parents[1] / "app/express_partner/templates/express_partner/partials/search_feed.html"


def test_card_price_matches_app():
    assert card_price("") == "توافقی"
    assert card_price("5500000000") == "۵،۵۰۰،۰۰۰،۰۰۰ تومان"
    assert card_price("۱٬۲۰۰٬۰۰۰") == "۱،۲۰۰،۰۰۰ تومان"
    assert card_price("۲.۵ میلیارد") == "۲.۵ میلیارد"


def test_card_area_and_place_match_app():
    assert card_area("86") == "۸۶ متر"
    assert card_area("400 متر") == "۴۰۰ متر"
    assert card_area("حدود ۲۰۰ متر") == "حدود ۲۰۰ متر"
    assert card_area("") == ""
    assert card_place({"city": "تهران", "location": "جیهون"}) == "در تهران، جیهون"
    assert card_place({"city": "کرج", "location": "کرج"}) == "در کرج"
    assert card_place({"location": "۲ ساعت پیش در تهران"}) == "۲ ساعت پیش در تهران"
    assert card_fields({"price_total": 15000000000, "size": "86"})["card_price"] == "۱۵،۰۰۰،۰۰۰،۰۰۰ تومان"


def test_hidden_skeleton_is_not_forced_visible():
    css = FEED.read_text(encoding="utf-8")
    assert "#vinorSearchPage .vn-search-list[hidden] { display: none; }" in css
    assert "--vn-search-chrome: #141416;" in css


def test_footer_has_follow_not_ai_chat():
    from pathlib import Path

    nav = Path("app/express_partner/templates/express_partner/partials/bottom_nav.html").read_text(encoding="utf-8")
    assert 'data-divar-tab="follow"' in nav and "پیگیری" in nav
    assert 'data-divar-tab="chat"' not in nav and "AI چت" not in nav


def test_listing_detail_footer_has_call_not_chat():
    from pathlib import Path

    tpl = Path("app/express_partner/templates/express_partner/listing_detail_native.html").read_text(encoding="utf-8")
    assert 'href="tel:{{ d.call_phone }}"' in tpl and ">تماس<" in tpl
    assert ">گفتگو<" not in tpl



def test_home_feed_hides_total_and_area_without_resizing_cards():
    markup = FEED.read_text(encoding="utf-8")
    assert 'id="vinorSearchCount"' not in markup
    assert 'class="vn-search-count"' not in markup
    assert 'min-height: 128px;' in markup
    assert 'width: 6.5rem;' in markup and 'height: 6.5rem;' in markup
    assert 'vn-search-area--spacer' in markup
    assert 'visibility: hidden;' in markup
    assert 'aria-hidden="true">&nbsp;</p>' in markup
    assert '<p class="vn-search-area">{{ _area }}</p>' not in markup
    assert '{% if _area %}، {{ _area }}{% endif %}' not in markup
    # The area filter stays usable even though the card no longer shows an area line.
    assert 'data-open-sheet="area"' in markup
