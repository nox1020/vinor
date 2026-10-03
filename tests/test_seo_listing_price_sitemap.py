# -*- coding: utf-8 -*-
"""Listing structured-data prices are rials, and the sitemap is public-only."""
from __future__ import annotations

from flask import Flask

from app.utils.seo import SITE_ORIGIN, build_land_seo, build_sitemap_entries

_CANONICAL = f"{SITE_ORIGIN}/express/partner/lands/V1"


def _land(code: str, **extra) -> dict:
    row = {
        "code": code,
        "title": "آپارتمان",
        "is_express": True,
        "express_status": "approved",
        "city": "تهران",
        "owner": "09120000000",
        "public": True,
    }
    row.update(extra)
    return row


def _offer(seo: dict) -> dict:
    offers = seo["json_ld"].get("offers")
    assert isinstance(offers, dict)
    return offers


def test_structured_price_is_toman_times_ten_irr():
    toman = 25_000_000
    seo = build_land_seo(_land("V1", price_total=toman), canonical_url=_CANONICAL)
    offer = _offer(seo)
    assert offer["price"] == toman * 10
    assert offer["priceCurrency"] == "IRR"
    assert seo["price"] == toman * 10
    assert seo["currency"] == "IRR"
    assert "25 میلیون تومان" in seo["description"]


def test_structured_price_reads_price_toman_when_that_is_the_stored_value():
    toman = 1_500_000
    seo = build_land_seo(
        _land("V1", price_toman=toman),
        canonical_url=_CANONICAL,
    )
    offer = _offer(seo)
    assert offer["price"] == toman * 10
    assert offer["priceCurrency"] == "IRR"
    assert seo["price"] == toman * 10


def test_structured_price_omits_missing_zero_and_non_numeric():
    for raw in (None, 0, 0.0, "", "0", "abc", "12 تومان", True):
        land = _land("V1")
        land.pop("price_total", None)
        land["price_total"] = raw
        seo = build_land_seo(land, canonical_url=_CANONICAL)
        assert "offers" not in seo["json_ld"], raw
        assert not seo["price"], raw
        assert seo["currency"] == "IRR"


def test_sitemap_lists_public_listing_and_skips_hidden_closed_sold(monkeypatch):
    lands = [
        _land("PUB1"),
        _land("HID1", express_status="hidden"),
        _land("CLS1", express_status="closed"),
        _land("SLD1", express_status="sold"),
        _land("PRV1", public=False),
        _land("ARC1", express_status="archived"),
    ]
    monkeypatch.setattr("app.utils.seo._homepage_lastmod", lambda: "2026-01-01")
    monkeypatch.setattr(
        "app.utils.storage.load_express_lands_cached",
        lambda app=None: lands,
    )

    locs = [item["loc"] for item in build_sitemap_entries(Flask(__name__))]

    def listed(code: str) -> bool:
        needle = f"/express/partner/lands/{code}"
        return any(loc.endswith(needle) for loc in locs)

    assert listed("PUB1")
    assert not listed("HID1")
    assert not listed("CLS1")
    assert not listed("SLD1")
    assert not listed("PRV1")
    assert not listed("ARC1")
