# -*- coding: utf-8 -*-
"""آمار هفتهٔ اول، پیامک ۷۲ساعته، و سهم بازدید ظرف ۷ روز."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.utils.dates import iso_z, utcnow


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("VINOR_LISTING_QUIET_NUDGE", "1")
    monkeypatch.setenv("VINOR_FOUNDATION_ENABLED", "1")
    monkeypatch.setenv("VINOR_ACTIVITY_STORE_ENABLED", "1")
    monkeypatch.setenv("VINOR_HARDENING_ENABLED", "1")
    monkeypatch.setenv("VINOR_HARDENING_OS_KPIS_ENABLED", "1")
    monkeypatch.delenv("LANDS_FILE", raising=False)
    return tmp_path


def _publish(phone="09120000000", **fields):
    from app.listings.service import create_listing, publish_listing

    created = create_listing(
        {"title": "زمین هفته اول", "city": "کرج", "price_total": 2_000_000, **fields},
        owner=phone,
    )
    code = str(created["code"])
    published, err, changed = publish_listing(
        phone,
        payment_method="نقدی",
        commission_pct=2,
        land_code=code,
    )
    assert err is None and changed is True
    return published


def _stamp(code, published_at, first_published_at=None):
    from app.listings.service import code_key, load_listings, save_listings

    rows = load_listings()
    for row in rows:
        if not isinstance(row, dict) or code_key(row) != str(code):
            continue
        row["published_at"] = published_at
        extras = dict(row.get("extras") or {})
        extras["published_at"] = published_at
        if first_published_at:
            row["first_published_at"] = first_published_at
            extras["first_published_at"] = first_published_at
        row["extras"] = extras
    save_listings(rows)


def test_publish_stamps_cycle_and_keeps_first(home):
    from app.listings.service import publish_listing, unpublish_listing

    first = _publish()
    code = str(first["code"])
    assert first["published_at"]
    assert first["first_published_at"] == first["published_at"]
    assert first["extras"]["published_at"] == first["published_at"]

    hidden, err, changed = unpublish_listing("09120000000", land_code=code)
    assert err is None and changed is True
    assert hidden["first_published_at"] == first["first_published_at"]

    again, again_err, again_changed = publish_listing(
        "09120000000",
        payment_method="توافقی",
        commission_pct=0,
        land_code=code,
    )
    assert again_err is None and again_changed is True
    assert again["first_published_at"] == first["first_published_at"]
    assert again["published_at"] != first["published_at"]
    assert again["extras"]["first_published_at"] == first["first_published_at"]


def test_stats_count_unique_views_and_visits_since_publish(home):
    from app.listings.performance import listing_performance
    from app.utils.storage import save_express_partner_views, save_express_visit_requests

    land = _publish(images=["a.jpg", "b.jpg"])
    code = str(land["code"])
    start = utcnow() - timedelta(days=3)
    _stamp(code, iso_z(start), first_published_at=iso_z(start - timedelta(days=30)))
    from app.listings.service import get_listing

    land = get_listing(code)
    old = iso_z(start - timedelta(days=2))
    recent = iso_z(start + timedelta(days=1))
    save_express_partner_views([
        {"timestamp": old, "code": code, "ip": "1.1.1.1"},
        {"timestamp": recent, "code": code, "ip": "1.1.1.1"},
        {"timestamp": recent, "code": code, "ip": "1.1.1.1"},
        {"timestamp": iso_z(utcnow()), "code": code, "ip": "2.2.2.2"},
        {"timestamp": recent, "code": "other", "ip": "3.3.3.3"},
    ])
    save_express_visit_requests([
        {"land_code": code, "created_at": old, "status": "approved"},
        {"land_code": code, "created_at": recent, "status": "approved"},
        {"land_code": code, "created_at": iso_z(utcnow() - timedelta(days=10)), "status": "approved"},
        {"land_code": "other", "created_at": recent, "status": "approved"},
    ])
    stats = listing_performance(land, now=utcnow())
    assert stats["views_since_publish"] == 2
    assert stats["weekly_views"] == 2
    assert stats["visit_requests_total"] == 1
    assert stats["visit_requests_7d"] == 1
    assert stats["published_at"] == iso_z(start)
    assert stats["days_since_publish"] == 3
    assert stats["first_published_at"] == iso_z(start - timedelta(days=30))


def test_payload_uses_real_stats_and_drops_fake_market_numbers(home):
    from app.express_partner.my_property import demo_property, page_payload, property_cards
    from app.utils.storage import save_express_partner_views, save_express_visit_requests

    land = _publish()
    code = str(land["code"])
    start = utcnow() - timedelta(days=1)
    _stamp(code, iso_z(start))
    save_express_partner_views([
        {"timestamp": iso_z(utcnow()), "code": code, "ip": "9.9.9.9"},
    ])
    save_express_visit_requests([
        {"land_code": code, "created_at": iso_z(utcnow()), "status": "approved"},
    ])

    page = page_payload("09120000000")
    assert page["weekly_views"] == 1
    assert page["views_since_publish"] == 1
    assert page["visit_requests_7d"] == 1
    assert page["visit_requests_total"] == 1
    assert page["published_at"]
    assert page["days_since_publish"] == 1
    prop = page["property"]
    assert prop["monthly_change_pct"] is None
    assert prop["yearly_change_pct"] is None
    assert prop["equity"]["paid_off_pct"] is None
    assert prop["neighborhood_avg"] is None
    assert prop["price_history"] == []
    assert prop["estimated_value"] == 2_000_000
    assert all("قیمت تخمینی" not in str(row.get("text")) for row in prop["activity"])
    assert any(row["type"] == "publish" for row in prop["activity"])
    card = page["items"][0]
    assert card["weekly_views"] == 1
    assert card["visit_requests_total"] == 1
    assert card["monthly_change_pct"] is None
    assert property_cards("09120000000")[0]["views_since_publish"] == 1

    demo = demo_property()
    assert demo["estimated_value"] is None
    assert demo["monthly_change_pct"] is None
    assert demo["weekly_views"] == 0
    assert demo["equity"]["paid_off_pct"] is None
    assert demo["activity"] == []
    assert demo["price_history"] == []


def test_quiet_sms_fires_once_per_publish_cycle(home):
    from app.listings.quiet_nudge import maybe_send_quiet_listing_nudges
    from app.listings.service import get_listing, publish_listing, unpublish_listing
    from app.utils.storage import save_express_partner_views, save_express_visit_requests

    land = _publish(images=[])
    code = str(land["code"])
    now = utcnow()
    old_cycle = iso_z(now - timedelta(hours=73))
    _stamp(code, old_cycle, first_published_at=old_cycle)
    save_express_partner_views([
        {"timestamp": iso_z(now - timedelta(hours=10)), "code": code, "ip": "4.4.4.4"},
        {"timestamp": iso_z(now - timedelta(hours=9)), "code": code, "ip": "5.5.5.5"},
    ])
    sent = []

    def sender(phone, message):
        sent.append((phone, message))
        return {"ok": True}

    too_soon = iso_z(now - timedelta(hours=71))
    _stamp(code, too_soon, first_published_at=old_cycle)
    assert maybe_send_quiet_listing_nudges(now=now, sender=sender) == []
    assert sent == []

    _stamp(code, old_cycle, first_published_at=old_cycle)
    save_express_visit_requests([
        {"land_code": code, "created_at": iso_z(now - timedelta(hours=1)), "status": "approved"},
    ])
    assert maybe_send_quiet_listing_nudges(now=now, sender=sender) == []
    assert sent == []

    save_express_visit_requests([])
    first = maybe_send_quiet_listing_nudges(now=now, sender=sender)
    assert len(first) == 1
    assert first[0]["phone"] == "09120000000"
    assert "۲" in first[0]["message"]
    assert "عکس" in first[0]["message"]
    assert "ملک من:" in first[0]["message"]
    assert maybe_send_quiet_listing_nudges(now=now, sender=sender) == []
    assert len(sent) == 1
    assert get_listing(code)["extras"]["quiet_nudge_published_at"] == old_cycle

    hidden, err, changed = unpublish_listing("09120000000", land_code=code)
    assert err is None and changed is True
    again, again_err, again_changed = publish_listing(
        "09120000000",
        payment_method="نقدی",
        commission_pct=2,
        land_code=code,
    )
    assert again_err is None and again_changed is True
    new_cycle = iso_z(now - timedelta(hours=80))
    _stamp(code, new_cycle, first_published_at=old_cycle)
    from app.listings.service import load_listings, save_listings, code_key

    rows = load_listings()
    for row in rows:
        if isinstance(row, dict) and code_key(row) == code:
            row["images"] = ["a.jpg", "b.jpg"]
            extras = dict(row.get("extras") or {})
            extras["express_commission_pct"] = 2
            row["extras"] = extras
    save_listings(rows)
    second = maybe_send_quiet_listing_nudges(now=now, sender=sender)
    assert len(second) == 1
    assert "بالاتر" in second[0]["message"]
    assert len(sent) == 2
    assert get_listing(code)["first_published_at"] == old_cycle
    assert get_listing(code)["extras"]["quiet_nudge_published_at"] == new_cycle


def test_publish_and_visit_write_activities(home):
    from app.express_partner.visit_requests import create_visit_request
    from app.foundation.activity_store import list_activities
    from app.listings.service import code_key

    land = _publish()
    code = str(land["code"])
    published = [
        row for row in list_activities(land_code=code, limit=20) if row.action == "listing_published"
    ]
    assert published
    assert published[0].actor_role == "owner"

    day = (utcnow() + timedelta(days=1)).date()
    while day.weekday() > 4:
        day += timedelta(days=1)
    rec, err = create_visit_request(
        [],
        partner_phone="09121111111",
        partner_name="همکار",
        land_code=code,
        land_title="زمین هفته اول",
        visit_date=day.isoformat(),
        customer_first_name="علی",
        customer_last_name="رضایی",
        customer_phone="09123333333",
        visit_time="10",
    )
    assert err is None and rec
    assert code_key({"code": rec["land_code"]}) == code
    visits = [
        row for row in list_activities(land_code=code, limit=20) if row.action == "listing_visit_requested"
    ]
    assert visits
    assert visits[0].actor_role == "partner"


def test_publish_to_visit_kpi_uses_completed_seven_day_window(home):
    from app.hardening.os_kpis import compute_os_kpis
    from app.listings.service import create_listing, save_listings, load_listings
    from app.utils.storage import save_express_visit_requests

    now = utcnow()
    hit_at = iso_z(now - timedelta(days=10))
    miss_at = iso_z(now - timedelta(days=12))
    fresh_at = iso_z(now - timedelta(days=2))
    rows = []
    for code, phone, stamp in (
        ("71", "09120000071", hit_at),
        ("72", "09120000072", miss_at),
        ("73", "09120000073", fresh_at),
    ):
        rows.append(create_listing(
            {
                "title": code,
                "code": code,
                "price_total": 1,
                "published_at": stamp,
                "first_published_at": stamp,
                "source": "my_property_published",
                "public": True,
                "is_express": True,
                "extras": {
                    "published_for_sale": True,
                    "published_at": stamp,
                    "first_published_at": stamp,
                    "listed_by_owner": True,
                },
            },
            owner=phone,
        ))
    # create_listing forces a private home unless flags say otherwise; restamp after save.
    stored = load_listings()
    for row in stored:
        code = str(row.get("code"))
        stamp = {"71": hit_at, "72": miss_at, "73": fresh_at}[code]
        row["published_at"] = stamp
        row["first_published_at"] = stamp
        row["source"] = "my_property_published"
        row["public"] = True
        row["is_express"] = True
        extras = dict(row.get("extras") or {})
        extras.update({
            "published_for_sale": True,
            "published_at": stamp,
            "first_published_at": stamp,
            "listed_by_owner": True,
            "public": True,
        })
        row["extras"] = extras
    save_listings(stored)
    save_express_visit_requests([
        {"land_code": "71", "created_at": iso_z(now - timedelta(days=9))},
        {"land_code": "72", "created_at": iso_z(now - timedelta(days=1))},
        {"land_code": "73", "created_at": iso_z(now - timedelta(days=1))},
    ])
    kpis = compute_os_kpis()
    assert kpis["published_measured_count"] == 2
    assert kpis["published_with_visit_7d_count"] == 1
    assert kpis["publish_to_visit_7d_rate"] == 0.5


def _write_store(home, name, text):
    folder = home / "data"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def test_legacy_listing_without_published_at_stays_quiet(home):
    from app.express_partner.my_property import page_payload
    from app.listings.performance import listing_performance
    from app.listings.quiet_nudge import maybe_send_quiet_listing_nudges
    from app.listings.service import create_listing, load_listings, save_listings

    private = create_listing({"title": "قدیمی", "price_total": 10}, owner="09120000000")
    stats = listing_performance(private)
    assert stats["published_at"] is None
    assert stats["first_published_at"] is None
    assert stats["days_since_publish"] is None
    assert stats["weekly_views"] == 0
    assert stats["visit_requests_total"] == 0

    rows = load_listings()
    rows.append({
        "code": "legacy",
        "owner": "09120000000",
        "title": "منتشرِ بی‌تاریخ",
        "source": "my_property_published",
        "public": True,
        "is_express": True,
        "extras": {"published_for_sale": True, "listed_by_owner": True, "published_at": "not-a-date"},
    })
    save_listings(rows)
    legacy = next(row for row in load_listings() if str(row.get("code")) == "legacy")
    quiet = listing_performance(legacy, views=[{"code": "legacy", "ip": "1.1.1.1", "timestamp": "2026-10-01T00:00:00Z"}])
    assert quiet["published_at"] is None
    assert quiet["views_since_publish"] == 0
    sent = []
    assert maybe_send_quiet_listing_nudges(
        now=utcnow() + timedelta(days=30),
        sender=lambda phone, message: sent.append(phone) or {"ok": True},
    ) == []
    assert sent == []
    page = page_payload("09120000000")
    assert page["items"]
    assert all(item["published_at"] is None or item["code"] != "legacy" for item in page["items"])


def test_missing_and_corrupt_view_and_visit_files(home):
    from app.listings.performance import listing_performance
    from app.listings.quiet_nudge import maybe_send_quiet_listing_nudges

    land = _publish(images=["a.jpg", "b.jpg"])
    code = str(land["code"])
    now = utcnow()
    _stamp(code, iso_z(now - timedelta(hours=80)))
    land = __import__("app.listings.service", fromlist=["get_listing"]).get_listing(code)

    assert listing_performance(land, now=now)["weekly_views"] == 0
    assert listing_performance(land, now=now)["visit_requests_total"] == 0

    _write_store(home, "express_partner_views.json", "{not json")
    _write_store(home, "express_visit_requests.json", "")
    assert listing_performance(land, now=now)["views_since_publish"] == 0
    sent = []
    assert maybe_send_quiet_listing_nudges(
        now=now,
        sender=lambda phone, message: sent.append(message) or {"ok": True},
    ) == []
    assert sent == []

    _write_store(home, "express_visit_requests.json", '{"no": "list"}')
    _write_store(home, "express_partner_views.json", '{"1.1.1.1": 3}')
    assert listing_performance(land, now=now)["weekly_views"] == 0
    assert maybe_send_quiet_listing_nudges(now=now, sender=lambda *a: {"ok": True}) == []

    _write_store(home, "express_partner_views.json", json_dup(code))
    _write_store(home, "express_visit_requests.json", "[]")
    from_file = listing_performance(land, now=now)
    assert from_file["views_since_publish"] == 1
    assert from_file["visit_requests_total"] == 0
    stats = listing_performance(
        land,
        now=now,
        views=[
            {"code": code, "ip": "1.1.1.1", "timestamp": iso_z(now - timedelta(hours=2))},
            {"code": code, "ip": "1.1.1.1", "timestamp": iso_z(now - timedelta(hours=1))},
            {"code": code, "ip": " 1.1.1.1 ", "timestamp": iso_z(now - timedelta(hours=1))},
            {"code": code, "ip": "", "timestamp": iso_z(now)},
            "not-a-row",
            {"code": code, "ip": "8.8.8.8", "timestamp": iso_z(now - timedelta(days=8))},
            {"code": code, "ip": "9.9.9.9", "timestamp": iso_z(now - timedelta(hours=3))},
        ],
    )
    assert stats["views_since_publish"] == 2
    assert stats["weekly_views"] == 2


def json_dup(code):
    import json
    return json.dumps([
        {"code": code, "ip": "1.1.1.1", "timestamp": "2026-10-17T00:00:00Z"},
        {"code": code, "ip": "1.1.1.1", "timestamp": "2026-10-17T01:00:00Z"},
    ])


def test_timezone_offset_counts_as_utc(home):
    from app.listings.performance import listing_performance
    from app.listings.quiet_nudge import maybe_send_quiet_listing_nudges
    from app.listings.service import get_listing

    land = _publish(images=["a.jpg", "b.jpg"])
    code = str(land["code"])
    # ۱۲:۰۰ به وقت تهران = ۰۸:۳۰ UTC
    _stamp(code, "2026-10-14T12:00:00+03:30", first_published_at="2026-10-14T12:00:00+03:30")
    land = get_listing(code)
    now = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)
    stats = listing_performance(
        land,
        now=now,
        views=[
            {"code": code, "ip": "1.1.1.1", "timestamp": "2026-10-16T12:00:00+03:30"},
            {"code": code, "ip": "2.2.2.2", "timestamp": "2026-10-13T12:00:00+03:30"},
        ],
        visits=[],
    )
    assert stats["days_since_publish"] == 3
    assert stats["views_since_publish"] == 1
    assert stats["weekly_views"] == 1
    assert stats["published_at"] == "2026-10-14T12:00:00+03:30"

    almost = datetime(2026, 10, 17, 8, 29, 59, tzinfo=timezone.utc)
    assert maybe_send_quiet_listing_nudges(now=almost, sender=lambda *a: {"ok": True}) == []
    sent = maybe_send_quiet_listing_nudges(now=now, sender=lambda *a: {"ok": True})
    assert len(sent) == 1


def test_unpublish_before_72h_and_failed_sender_can_retry(home):
    from app.listings.quiet_nudge import maybe_send_quiet_listing_nudges
    from app.listings.service import get_listing, unpublish_listing

    land = _publish(images=["a.jpg", "b.jpg"])
    code = str(land["code"])
    now = utcnow()
    _stamp(code, iso_z(now - timedelta(hours=80)))

    hidden, err, changed = unpublish_listing("09120000000", land_code=code)
    assert err is None and changed is True
    assert get_listing(code)["published_at"]
    assert maybe_send_quiet_listing_nudges(now=now, sender=lambda *a: {"ok": True}) == []

    from app.listings.service import publish_listing

    again, again_err, again_changed = publish_listing(
        "09120000000",
        payment_method="نقدی",
        commission_pct=2,
        land_code=code,
    )
    assert again_err is None and again_changed is True
    cycle = iso_z(now - timedelta(hours=73))
    _stamp(code, cycle, first_published_at=get_listing(code)["first_published_at"])

    def boom(phone, message):
        raise RuntimeError("sms down")

    assert maybe_send_quiet_listing_nudges(now=now, sender=boom) == []
    assert "quiet_nudge_published_at" not in (get_listing(code).get("extras") or {})

    assert maybe_send_quiet_listing_nudges(now=now, sender=lambda *a: {"ok": False}) == []
    assert "quiet_nudge_published_at" not in (get_listing(code).get("extras") or {})

    sent = maybe_send_quiet_listing_nudges(now=now, sender=lambda *a: {"ok": True})
    assert len(sent) == 1
    assert get_listing(code)["extras"]["quiet_nudge_published_at"] == cycle


def test_two_scheduler_ticks_send_one_sms(home):
    from app.listings.quiet_nudge import maybe_send_quiet_listing_nudges

    land = _publish(images=["a.jpg", "b.jpg"])
    code = str(land["code"])
    now = utcnow()
    _stamp(code, iso_z(now - timedelta(hours=80)))
    sent = []
    gate = threading.Barrier(2)

    def sender(phone, message):
        sent.append(phone)
        try:
            gate.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
        return {"ok": True}

    errors = []

    def run():
        try:
            maybe_send_quiet_listing_nudges(now=now, sender=sender)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert errors == []
    assert sent == ["09120000000"]


def test_quiet_nudge_is_on_the_reach_scheduler():
    from app.reach import scheduler

    assert "run_listing_quiet_nudge" in scheduler._loop.__code__.co_names or any(
        "run_listing_quiet_nudge" in getattr(const, "co_names", ())
        for const in scheduler._loop.__code__.co_consts
        if hasattr(const, "co_names")
    )
    called = {}

    def fake():
        called["yes"] = True

    import app.listings.quiet_nudge as quiet

    previous = quiet.maybe_send_quiet_listing_nudges
    quiet.maybe_send_quiet_listing_nudges = fake
    try:
        scheduler.run_listing_quiet_nudge()
    finally:
        quiet.maybe_send_quiet_listing_nudges = previous
    assert called.get("yes") is True
