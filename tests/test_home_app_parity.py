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
