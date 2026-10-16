# -*- coding: utf-8 -*-
"""یک فایل برای آگهی: ساخت، انتشار، توقف، انتشار دوباره، ویرایش، مهاجرت."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.delenv("LANDS_FILE", raising=False)
    return tmp_path


def _codes(rows):
    return sorted(str(row.get("code") or "") for row in rows if isinstance(row, dict))


def test_create_publish_unpublish_republish_and_edit(home):
    from app.listings.service import (
        create_listing,
        get_listing,
        is_private_owner_home,
        is_published_for_sale,
        publish_listing,
        unpublish_listing,
        update_listing,
    )
    from app.utils.storage import load_ads, load_express_lands_cached

    created = create_listing(
        {
            "title": "زمین تست یکپارچه",
            "city": "کرج",
            "price_total": 2_000_000,
            "images": ["a.jpg"],
        },
        owner="09120000000",
    )
    code = str(created["code"])
    assert code
    assert is_private_owner_home(created)
    assert is_published_for_sale(created) is False
    assert code not in _codes(load_express_lands_cached())

    published, err, changed = publish_listing(
        "989120000000",
        payment_method="نقدی",
        commission_pct=2,
        land_code=code,
    )
    assert err is None and changed is True
    assert is_published_for_sale(published)
    assert published["public"] is True
    assert published["is_express"] is True
    assert published["source"] == "my_property_published"
    assert published["extras"]["published_for_sale"] is True
    assert published["payment_method"] == "نقدی"
    assert code in _codes(load_express_lands_cached())

    hidden, stop_err, stopped = unpublish_listing("09120000000", land_code=code)
    assert stop_err is None and stopped is True
    assert is_private_owner_home(hidden)
    assert hidden["is_express"] is False
    assert hidden["extras"]["published_for_sale"] is False
    assert hidden["payment_method"] == "نقدی"
    assert code not in _codes(load_express_lands_cached())
    assert get_listing(code)["title"] == "زمین تست یکپارچه"

    again, again_err, again_changed = publish_listing(
        "09120000000",
        payment_method="توافقی",
        commission_pct=0,
        land_code=code,
    )
    assert again_err is None and again_changed is True
    assert is_published_for_sale(again)
    assert again["payment_method"] == "توافقی"
    assert code in _codes(load_express_lands_cached())

    edited = update_listing(
        code,
        {"title": "زمین ویرایش‌شده", "source": "express", "public": False},
        owner="09120000000",
    )
    assert edited["title"] == "زمین ویرایش‌شده"
    assert edited["code"] == code
    assert edited["source"] == "my_property_published"
    assert edited["public"] is True
    stored = load_ads()
    assert [row for row in stored if row.get("code") == code][0]["title"] == "زمین ویرایش‌شده"
    assert sum(1 for row in stored if row.get("code") == code) == 1


def test_inconsistent_publish_flags_become_one_state(home):
    from app.listings.service import is_published_for_sale
    from app.utils.storage import load_ads, load_express_lands_cached, save_ads

    save_ads([
        {
            "code": "7",
            "title": "علامت‌های ناسازگار",
            "owner": "09123333333",
            "public": True,
            "is_express": False,
            "source": "my_property",
            "extras": {"listed_by_owner": True, "published_for_sale": False},
        }
    ])
    row = [item for item in load_ads() if item.get("code") == "7"][0]
    assert is_published_for_sale(row)
    assert row["is_express"] is True
    assert row["source"] == "my_property_published"
    assert row["extras"]["published_for_sale"] is True
    assert "7" in _codes(load_express_lands_cached())


def test_migration_merges_copies_and_keeps_every_code(home, monkeypatch):
    legacy = home / "legacy-data"
    legacy.mkdir()
    canonical = home / "data"
    canonical.mkdir()
    (canonical / "lands.json").write_text(json.dumps([
        {"code": "1", "title": "اول", "owner": "09120000000", "description": ""},
        {
            "code": "2",
            "owner": "09120000000",
            "title": "ملک حیاط‌دار",
            "images": ["a.jpg"],
            "source": "my_property",
            "is_express": False,
            "public": False,
            "owner_home": True,
            "extras": {"owner_home": True, "listed_by_owner": True, "published_for_sale": False},
        },
        {
            "code": "2",
            "owner": "989120000000",
            "title": "",
            "description": "حیاط",
            "images": ["b.jpg"],
            "source": "my_property",
            "is_express": False,
            "public": False,
            "owner_home": True,
            "extras": {"owner_home": True, "listed_by_owner": True, "published_for_sale": False},
        },
    ], ensure_ascii=False), encoding="utf-8")
    (legacy / "lands.json").write_text(json.dumps([
        {"code": "1", "owner": "09120000000", "description": "از فایل قدیمی", "title": ""},
        {
            "code": "3",
            "title": "فقط در فایل قدیمی",
            "owner": "09121111111",
            "is_express": True,
            "public": True,
            "source": "express",
        },
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("app.utils.storage.legacy_dir", lambda app=None: str(legacy))

    from app.listings.service import load_listings

    rows = [row for row in load_listings() if isinstance(row, dict)]
    by_code = {str(row.get("code")): row for row in rows}
    assert set(by_code) >= {"1", "2", "3"}
    assert by_code["1"]["description"] == "از فایل قدیمی"
    assert by_code["1"]["title"] == "اول"
    assert by_code["2"]["title"] == "ملک حیاط‌دار"
    assert by_code["2"]["description"] == "حیاط"
    assert by_code["2"]["images"] == ["a.jpg", "b.jpg"]
    assert by_code["3"]["title"] == "فقط در فایل قدیمی"
    assert sum(1 for row in rows if str(row.get("code")) == "2") == 1
    assert (canonical / "lands.json.legacy").is_file()
