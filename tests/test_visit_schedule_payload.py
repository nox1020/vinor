# -*- coding: utf-8 -*-
"""تقویم بازدید در tx-status همان landDetailConfig است."""
from __future__ import annotations

import pytest


PHONE = "09124000081"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-visit-calendar")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")

    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_schedule_payload_matches_land_detail_config():
    from app.express_partner.land_detail_config import build_land_detail_config
    from app.express_partner.visit_requests import (
        get_visit_allowed_hours,
        visit_allowed_weekdays_for_js,
        visit_date_min_iso,
        visit_schedule_for_land,
    )

    schedule = visit_schedule_for_land("land-12")
    config = build_land_detail_config(
        {"code": "land-12", "title": "فایل"},
        images=[],
        has_video=False,
        total_items=0,
        share_url="",
        is_approved=True,
        visit_date_min=visit_date_min_iso(),
        visit_allowed_weekdays_js=visit_allowed_weekdays_for_js(),
        visit_allowed_hours=get_visit_allowed_hours(),
        flash_messages=[],
        tx_status_url="/express/partner/lands/land-12/tx-status",
        csrf_token="token",
    )
    assert schedule["visit_date_min"] == config["visitDateMin"]
    assert schedule["visit_date_min"]
    assert schedule["visit_allowed_weekdays"] == config["visitAllowedWeekdays"]
    assert schedule["visit_allowed_hours"] == config["visitAllowedHours"]
    assert schedule["visit_allowed_hours"]
    assert all(isinstance(hour, int) and 0 <= hour <= 23 for hour in schedule["visit_allowed_hours"])
    assert all(isinstance(day, int) and 0 <= day <= 6 for day in schedule["visit_allowed_weekdays"])
    assert schedule["visit_request_url"] == "/express/partner/visit-requests/land-12"


def test_tx_status_json_includes_the_same_calendar(client, monkeypatch):
    from app.express_partner import routes as ep_routes
    from app.express_partner.visit_requests import visit_schedule_for_land

    monkeypatch.setattr(ep_routes, "_express_land_in_catalog", lambda code: str(code) == "land-12")
    monkeypatch.setattr(ep_routes, "_is_partner_approved", lambda profile: True)
    monkeypatch.setattr(ep_routes, "_defer_routine_auto_tick", lambda *args, **kwargs: None)

    with client.session_transaction() as sess:
        sess["user_phone"] = PHONE

    response = client.get(
        "/express/partner/lands/land-12/tx-status",
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    expected = visit_schedule_for_land("land-12")
    assert body["visit_date_min"] == expected["visit_date_min"]
    assert body["visit_allowed_weekdays"] == expected["visit_allowed_weekdays"]
    assert body["visit_allowed_hours"] == expected["visit_allowed_hours"]
    assert body["visit_request_url"] == expected["visit_request_url"]
