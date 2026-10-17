# -*- coding: utf-8 -*-
"""صندوق پیگیری: مالک غیرپلاس، یک کارت برای هر فایل، لیست واحد."""
from __future__ import annotations

import threading
from datetime import date, timedelta

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.delenv("LANDS_FILE", raising=False)
    return tmp_path


def _future_days():
    day = date.today() + timedelta(days=1)
    for _ in range(21):
        yield day
        day += timedelta(days=1)


def _publish(phone="09121111111"):
    from app.listings.service import create_listing, publish_listing

    created = create_listing(
        {"title": "آگهی پیگیری", "city": "کرج", "price_total": 2_000_000},
        owner=phone,
    )
    code = str(created["code"])
    published, err, changed = publish_listing(
        phone, payment_method="نقدی", commission_pct=2, land_code=code,
    )
    assert err is None and changed
    return published


def _request(code, requester="09123333333", customer="09120000099", day=None):
    from app.express_partner.visit_requests import create_visit_request

    rows = []
    last = None
    days = [day] if day is not None else list(_future_days())
    for item in days:
        rec, err = create_visit_request(
            rows,
            partner_phone=requester,
            partner_name="مشاور",
            land_code=code,
            land_title="آگهی پیگیری",
            visit_date=item.isoformat(),
            customer_first_name="علی",
            customer_last_name="رضایی",
            customer_phone=customer,
        )
        last = err
        if rec:
            return rows, rec
        if err not in ("weekday_not_allowed", "no_hours", "past_date"):
            break
    raise AssertionError(last)


def _plain(phone):
    return {"phone": phone, "status": "approved", "partner_tier": "partner", "name": "مالک"}


def _pipeline(phone, profile=None):
    from app.express_partner.routes import _build_partner_sales_pipeline

    return _build_partner_sales_pipeline(phone, profile if profile is not None else _plain(phone), land_status={})


def test_non_plus_owner_sees_incoming_visit(home):
    published = _publish()
    code = str(published["code"])
    rows, rec = _request(code)
    from app.utils.storage import save_express_visit_requests

    save_express_visit_requests(rows)
    assert rec.get("owner_phone") == "09121111111"
    assert "owner" not in rec or rec.get("owner") in (None, "")

    owner = _pipeline("09121111111")
    assert owner["is_special"] is False
    assert [item["id"] for item in owner["inbox_items"]] == [rec["id"]]
    assert owner["items"] == []
    card = owner["cards"][0]
    assert card["direction"] == "incoming"
    assert card["stage"] == "visit"
    assert card["stage_label"] == "بازدید"
    assert card["can_approve"] is False
    assert card["can_start_deal"] is False

    consultant = _pipeline("09123333333")
    assert consultant["inbox_items"] == []
    assert [item["id"] for item in consultant["items"]] == [rec["id"]]
    assert consultant["cards"][0]["direction"] == "outgoing"

    from app.express_partner.special_visit_inbox import visit_inbox_badge_count

    assert visit_inbox_badge_count("09121111111") == 1
    assert visit_inbox_badge_count("09123333333") == 0


def test_phone_only_and_owner_phone_only_listings(home):
    from app.utils.storage import load_ads, save_ads, save_express_visit_requests

    first = _publish("09121111111")
    code = str(first["code"])
    lands = load_ads()
    for land in lands:
        if str(land.get("code")) == code:
            land.pop("owner", None)
            land.pop("user_phone", None)
            land["phone"] = "09121111111"
    save_ads(lands)
    rows, rec = _request(code)
    save_express_visit_requests(rows)
    owner = _pipeline("09121111111")
    assert [item["id"] for item in owner["inbox_items"]] == [rec["id"]]

    second = _publish("09122222222")
    code2 = str(second["code"])
    lands = load_ads()
    for land in lands:
        if str(land.get("code")) == code2:
            land.pop("owner", None)
            land.pop("user_phone", None)
            land.pop("phone", None)
            land["owner_phone"] = "09122222222"
    save_ads(lands)
    rows2, rec2 = _request(code2, requester="09124444444", customer="09120000088")
    from app.utils.storage import load_express_visit_requests

    save_express_visit_requests(list(load_express_visit_requests() or []) + rows2)
    other = _pipeline("09122222222")
    assert [item["id"] for item in other["inbox_items"]] == [rec2["id"]]
    first_owner = _pipeline("09121111111")
    assert [item["id"] for item in first_owner["inbox_items"]] == [rec["id"]]


def test_previous_code_still_matches_owner_inbox(home):
    from app.utils.storage import load_ads, save_ads, save_express_visit_requests

    published = _publish()
    code = str(published["code"])
    rows, rec = _request(code)
    save_express_visit_requests(rows)
    lands = load_ads()
    for land in lands:
        if str(land.get("code")) == code:
            extras = dict(land.get("extras") or {})
            extras["previous_code"] = code
            land["extras"] = extras
            land["code"] = "9001"
    save_ads(lands)
    owner = _pipeline("09121111111")
    assert [item["id"] for item in owner["inbox_items"]] == [rec["id"]]
    assert owner["cards"][0]["land_code"] == code


def test_revisit_updates_same_card_and_keeps_history(home):
    from app.express_partner.visit_requests import create_visit_request

    published = _publish()
    code = str(published["code"])
    rows, first = _request(code)
    first_id = first["id"]
    first_date = first["visit_date"]
    later = date.fromisoformat(first_date) + timedelta(days=7)
    second, err = create_visit_request(
        rows,
        partner_phone="09123333333",
        partner_name="مشاور",
        land_code=code,
        land_title="آگهی پیگیری",
        visit_date=later.isoformat(),
        customer_first_name="علی",
        customer_last_name="رضایی",
        customer_phone="09120000099",
    )
    assert err is None and second
    assert second["id"] == first_id
    assert len(rows) == 1
    assert second["revisit_count"] == 1
    assert second["visit_date"] == later.isoformat()
    assert second["history"][0]["visit_date"] == first_date
    assert second["history"][0]["id"] == first_id
    assert second["updated_at"] >= first["created_at"]

    other, err = create_visit_request(
        rows,
        partner_phone="09123333333",
        partner_name="مشاور",
        land_code=code,
        land_title="آگهی پیگیری",
        visit_date=later.isoformat(),
        customer_first_name="سارا",
        customer_last_name="کریمی",
        customer_phone="09120000077",
    )
    assert err is None and other
    assert other["id"] != first_id
    assert len(rows) == 2


def test_read_time_collapse_keeps_both_visits_in_history(home):
    from app.express_partner.visit_requests import collapse_visit_rows
    from app.utils.storage import save_express_visit_requests

    published = _publish()
    code = str(published["code"])
    save_express_visit_requests([
        {
            "id": "old",
            "partner_phone": "09123333333",
            "land_code": code,
            "customer_phone": "09120000099",
            "status": "completed",
            "visit_date": "2026-01-01",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
        },
        {
            "id": "new",
            "partner_phone": "09123333333",
            "land_code": code,
            "customer_phone": "09120000099",
            "status": "approved",
            "visit_date": "2026-02-01",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-02T00:00:00Z",
        },
    ])
    pipe = _pipeline("09121111111")
    assert len(pipe["cards"]) == 1
    card = pipe["cards"][0]
    assert card["id"] == "new"
    assert any(item.get("id") == "old" for item in card["history"])
    collapsed = collapse_visit_rows([
        {"id": "old", "partner_phone": "09123333333", "land_code": code, "customer_phone": "09120000099", "updated_at": "1"},
        {"id": "new", "partner_phone": "09123333333", "land_code": code, "customer_phone": "09120000099", "updated_at": "2"},
    ])
    assert len(collapsed) == 1
    assert collapsed[0]["owner_phone"] == "09121111111"


def test_unified_list_order_stages_and_tab_counts(home):
    from app.utils.storage import save_express_visit_requests

    published = _publish()
    code = str(published["code"])
    save_express_visit_requests([
        {
            "id": "pending-one",
            "partner_phone": "09123333333",
            "partner_name": "مشاور",
            "land_code": code,
            "customer_phone": "09120000011",
            "customer_name": "یک",
            "status": "pending",
            "visit_date": "2026-03-01",
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-01T00:00:00Z",
        },
        {
            "id": "approved-two",
            "partner_phone": "09123333333",
            "partner_name": "مشاور",
            "land_code": code,
            "customer_phone": "09120000022",
            "customer_name": "دو",
            "status": "approved",
            "visit_date": "2026-03-02",
            "created_at": "2026-03-02T00:00:00Z",
            "updated_at": "2026-03-05T00:00:00Z",
        },
        {
            "id": "deal-three",
            "partner_phone": "09125555555",
            "partner_name": "دیگر",
            "land_code": code,
            "customer_phone": "09120000033",
            "status": "completed",
            "visit_outcome": "interested",
            "visit_date": "2026-03-03",
            "created_at": "2026-03-03T00:00:00Z",
            "updated_at": "2026-03-04T00:00:00Z",
        },
    ])
    owner = _pipeline("09121111111")
    assert [card["id"] for card in owner["cards"]] == ["approved-two", "deal-three", "pending-one"]
    stages = {card["id"]: card["stage"] for card in owner["cards"]}
    assert stages == {
        "pending-one": "visit_request",
        "approved-two": "visit",
        "deal-three": "deal",
    }
    assert owner["cards"][0]["stage_label"] == "بازدید"
    assert owner["tab_counts"] == {"requests": 1, "visits": 1, "deals": 1}
    assert all(card["direction"] == "incoming" for card in owner["cards"])


def test_submit_is_serialized_for_the_same_card(home):
    from app.express_partner.visit_requests import load_visit_requests_fresh, submit_visit_request

    published = _publish()
    code = str(published["code"])
    barrier = threading.Barrier(2)
    errors = []

    def send(day_offset):
        try:
            barrier.wait(timeout=5)
            day = date.today() + timedelta(days=day_offset)
            rec, err = submit_visit_request(
                partner_phone="09123333333",
                partner_name="مشاور",
                land_code=code,
                land_title="آگهی پیگیری",
                visit_date=day.isoformat(),
                customer_first_name="علی",
                customer_last_name="رضایی",
                customer_phone="09120000099",
            )
            if err:
                errors.append(err)
            return rec
        except Exception as exc:  # pragma: no cover
            errors.append(repr(exc))
            return None

    first = threading.Thread(target=send, args=(3,))
    second = threading.Thread(target=send, args=(10,))
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert errors == []
    rows = load_visit_requests_fresh()
    assert len(rows) == 1
    assert rows[0]["revisit_count"] == 1
    assert len(rows[0]["history"]) == 1
