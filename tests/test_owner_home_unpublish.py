# -*- coding: utf-8 -*-
"""توقف انتشار باید هر کپی ملک را خصوصی کند و جزئیات را منتشر نشان ندهد."""
from __future__ import annotations

from app.express_partner.special_listings import (
    apply_owner_publish,
    apply_owner_unpublish,
    detail_sale_flag,
    publish_terms,
    resolve_listing_for_viewer,
    unpublished_owner_home_only,
)


def _published(code="4", owner="09120000000", **extra):
    row = {
        "code": code,
        "owner": owner,
        "source": "my_property_published",
        "is_express": True,
        "public": True,
        "owner_home": False,
        "extras": {
            "published_for_sale": True,
            "listed_by_owner": True,
            "owner_home": False,
        },
    }
    row.update(extra)
    return row


def test_unpublish_clears_every_owned_copy_and_keeps_payment():
    first = _published()
    first["payment_method"] = "توافقی"
    first["extras"]["express_commission_pct"] = 0
    second = _published(is_express=True)
    other = _published(owner="09121111111")
    items = [first, second, other]
    rec, err, changed = apply_owner_unpublish(items, "989120000000", "4")
    assert err is None
    assert changed is True
    assert rec is first
    for row in (first, second):
        assert row["is_express"] is False
        assert row["public"] is False
        assert row["source"] == "my_property"
        assert row["extras"]["published_for_sale"] is False
        assert detail_sale_flag(row) is False
    assert first["payment_method"] == "توافقی"
    assert first["extras"]["express_commission_pct"] == 0
    assert other["is_express"] is True
    assert detail_sale_flag(other) is True


def test_unpublish_blank_or_foreign_code_is_not_found():
    items = [_published()]
    assert apply_owner_unpublish(items, "09120000000", "")[1] == "not_found"
    assert apply_owner_unpublish(items, "09123333333", "4")[1] == "not_found"
    assert items[0]["is_express"] is True


def test_second_unpublish_does_not_mark_a_change():
    items = [_published()]
    apply_owner_unpublish(items, "09120000000", "4")
    _rec, err, changed = apply_owner_unpublish(items, "۰۹۱۲۰۰۰۰۰۰۰", "4")
    assert err is None
    assert changed is False


def test_owner_detail_sees_private_row_not_a_live_duplicate():
    private = _published()
    apply_owner_unpublish([private], "09120000000", "4")
    live = _published()
    land, mode = resolve_listing_for_viewer([private, live], "4", "09120000000")
    assert mode == "owner"
    assert land is live
    assert detail_sale_flag(land) is True
    apply_owner_unpublish([private, live], "09120000000", "4")
    land, mode = resolve_listing_for_viewer([private, live], "4", "+98 912 000 0000")
    assert mode == "owner"
    assert detail_sale_flag(land) is False
    assert resolve_listing_for_viewer([private, live], "4", "09121111111")[0] is None
    assert unpublished_owner_home_only([private, live], "4") is True


def test_public_express_ad_stays_visible_and_flagged_on():
    ad = {
        "code": "9",
        "owner": "09124444444",
        "is_express": True,
        "public": True,
        "source": "express",
        "extras": {},
    }
    land, mode = resolve_listing_for_viewer([ad], "9", "09125555555")
    assert mode == "public"
    assert land is ad
    assert detail_sale_flag(ad) is True
    assert unpublished_owner_home_only([ad], "9") is False


def _private(code="4", owner="09120000000", **extra):
    row = {
        "code": code,
        "owner": owner,
        "source": "my_property",
        "is_express": False,
        "public": False,
        "owner_home": True,
        "price_total": 1_000_000,
        "extras": {
            "published_for_sale": False,
            "listed_by_owner": True,
            "owner_home": True,
        },
    }
    row.update(extra)
    return row


def test_publish_terms_allow_zero_and_reject_out_of_range():
    method, pct, err = publish_terms("نقدی", "0")
    assert err is None
    assert method == "نقدی"
    assert pct == 0
    assert publish_terms("نقدی", "-1")[2] == "invalid_commission"
    assert publish_terms("نقدی", "101")[2] == "invalid_commission"
    assert publish_terms("", "2")[2] == "payment_required"


def test_publish_updates_every_owned_copy_and_leaves_others():
    first = _private()
    second = _private(is_express=True)
    other = _private(owner="09121111111")
    stranger = {
        "code": "4",
        "owner": "09123333333",
        "source": "express",
        "is_express": True,
        "public": True,
        "extras": {},
    }
    rec, err, changed = apply_owner_publish(
        [first, second, other, stranger],
        "989120000000",
        "4",
        payment_method="توافقی",
        commission_pct=0,
    )
    assert err is None and changed is True
    assert rec is first
    for row in (first, second):
        assert row["extras"]["published_for_sale"] is True
        assert row["source"] == "my_property_published"
        assert row["payment_method"] == "توافقی"
        assert row["extras"]["express_commission_pct"] == 0
    assert other["extras"]["published_for_sale"] is False
    assert stranger.get("source") == "express"
    again, again_err, again_changed = apply_owner_publish(
        [first, second],
        "09120000000",
        "4",
        payment_method="نقدی",
        commission_pct=2,
    )
    assert again_err == "already_published"
    assert again_changed is False
    assert again["payment_method"] == "توافقی"
