# -*- coding: utf-8 -*-
"""Locks on consultant onboarding after web PR #4 (main 2dd1d4f).

Uses a throwaway INSTANCE_PATH, the Flask test client, and monkeypatch for env.
Does not call external services.
"""
from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import pytest

PHONE = "09124000071"
GATE = "/express/partner/consultant"
APPLY_PAGE = "/express/partner/consultant/apply"
PROFILE_PAGE = "/express/partner/consultant/profile"
DOCUMENTS_PAGE = "/express/partner/consultant/documents"
STATUS_PAGE = "/express/partner/consultant/status"
DASHBOARD_PAGE = "/express/partner/consultant/dashboard"
HOME_PAGE = "/express/partner/home"
OLD_APPLY_PAGE = "/express/partner/apply"
MARKETER_LABEL = "می‌خواهم بازاریاب وینور شوم"
LEGACY_LABEL = "همکاری با وینور"
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 32


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-consultant-locks")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.delenv("VINOR_CONSULTANT_DRY_RUN", raising=False)
    monkeypatch.delenv("VINOR_CONSULTANT_SIMULATE", raising=False)
    monkeypatch.delenv("VINOR_CONSULTANT_API_ENABLED", raising=False)

    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _body(resp, status: int):
    payload = resp.get_json(silent=True)
    assert resp.status_code == status, (resp.status_code, resp.get_data(as_text=True)[:800])
    assert isinstance(payload, dict), resp.get_data(as_text=True)[:800]
    return payload


def _location(resp) -> str:
    raw = resp.headers.get("Location") or ""
    return urlsplit(raw).path or raw


def _assert_redirect(resp, path: str) -> None:
    assert resp.status_code in (301, 302, 303, 307, 308), (resp.status_code, resp.get_data(as_text=True)[:400])
    assert _location(resp) == path, resp.headers.get("Location")


def _login(client, phone: str = PHONE) -> None:
    with client.session_transaction() as sess:
        sess["user_phone"] = phone
        sess.pop("logged_in", None)
        sess.pop("admin_phone", None)


def _stored_block(app, phone: str = PHONE) -> dict:
    with app.app_context():
        from app.express_partner.partner_session_sync import find_partner_record
        from app.utils.storage import load_express_partners

        record = find_partner_record(load_express_partners(), phone)
        assert isinstance(record, dict)
        block = record.get("consultant_onboarding")
        assert isinstance(block, dict)
        return block


def _apply_card(prompts: list) -> dict:
    matches = [item for item in prompts if item.get("intent") == "coop_apply"]
    assert len(matches) == 1, prompts
    return matches[0]


def test_dry_run_is_off_when_unset(monkeypatch):
    """Hotfix #2: an unset VINOR_CONSULTANT_DRY_RUN stays off, even if simulate is set."""
    monkeypatch.delenv("VINOR_CONSULTANT_DRY_RUN", raising=False)
    monkeypatch.setenv("VINOR_CONSULTANT_SIMULATE", "approved")

    from app.express_partner.consultant_onboarding import (
        coarse_status,
        dry_run_enabled,
        env_review_override,
        review_outcome,
    )

    assert os.environ.get("VINOR_CONSULTANT_DRY_RUN") is None
    assert dry_run_enabled() is False
    assert env_review_override() == ""
    block = {"review": "", "reject_reason": None}
    assert review_outcome(block) is None
    assert coarse_status(block) == "pending"


def test_partner_onboarding_locks(app, client):
    from app.express_partner.consultant_onboarding import dry_run_enabled

    assert os.environ.get("VINOR_CONSULTANT_DRY_RUN") is None
    assert dry_run_enabled() is False

    _login(client)
    _assert_redirect(client.get(GATE), APPLY_PAGE)

    applied = _body(client.post("/api/consultant/apply", json={}), 200)
    assert applied["ok"] is True
    assert applied["next_step"] == "profile"
    assert applied["status"] == "pending_profile"
    assert applied["role"] == "consultant"
    _assert_redirect(client.get(GATE), PROFILE_PAGE)

    cities = _body(client.get("/api/consultant/cities"), 200)
    rows = cities["cities"]
    assert cities["ok"] is True
    assert len(rows) == 15
    assert rows[0]["id"] == "tehran"
    assert len({row["id"] for row in rows}) == 15
    city_id = rows[0]["id"]

    profile = _body(
        client.patch(
            "/api/consultant/profile",
            json={"name": "نگار محمدی", "city": city_id, "specialties": ["buy"]},
        ),
        200,
    )
    assert profile["ok"] is True
    assert profile["next_step"] == "documents"
    assert profile["status"] == "pending_documents"
    assert profile["profile"]["city"] == "tehran"
    _assert_redirect(client.get(GATE), DOCUMENTS_PAGE)

    uploaded = _body(
        client.post(
            "/api/consultant/documents",
            data={"national_id": (BytesIO(_JPEG), "national-id.jpg")},
        ),
        200,
    )
    assert uploaded["ok"] is True
    assert uploaded["next_step"] == "status"
    assert uploaded["status"] == "pending"
    assert uploaded["documents"] == {
        "national_id": {"uploaded": True},
        "license": {"uploaded": False},
    }
    dumped = json.dumps(uploaded, ensure_ascii=False)
    assert "consultant_private" not in dumped
    assert PHONE not in dumped
    for item in uploaded["documents"].values():
        assert list(item) == ["uploaded"]
    private_files = list(Path(app.instance_path).joinpath("data", "consultant_private").rglob("national_id.*"))
    assert private_files, "national id must be stored outside the client payload"

    status = _body(client.get("/api/consultant/status"), 200)
    assert status["ok"] is True
    assert status["status"] == "pending"
    assert status["next_step"] == "status"
    assert status["documents_complete"] is True
    assert status["profile_complete"] is True
    assert status["online"] is False
    _assert_redirect(client.get(GATE), STATUS_PAGE)
    _assert_redirect(client.get(DASHBOARD_PAGE), STATUS_PAGE)

    availability = _body(client.post("/api/consultant/availability", json={"online": True}), 409)
    assert availability["ok"] is False
    assert availability["error"] == "not_approved"
    assert _stored_block(app).get("review") == "pending"
    assert _body(client.get("/api/consultant/status"), 200)["status"] == "pending"

    simulated = _body(client.get("/api/consultant/status?simulate=approved"), 200)
    assert simulated["ok"] is True
    assert simulated["status"] == "pending"
    assert simulated["next_step"] == "status"
    assert _stored_block(app).get("review") == "pending"
    assert _body(client.get("/api/consultant/status"), 200)["status"] == "pending"

    forged = _body(client.post("/api/consultant/simulate", json={"status": "approved"}), 400)
    assert forged["ok"] is False
    assert forged["error"] == "csrf_expired"
    assert forged.get("status") != "approved"
    assert _stored_block(app).get("review") == "pending"
    assert _body(client.get("/api/consultant/status"), 200)["next_step"] == "status"

    from app.express_partner.consultant_onboarding import apply_simulation

    with app.app_context():
        rejected, rejected_status = apply_simulation(PHONE, "rejected", "رد آزمایشی قفل")
    assert rejected_status == 200
    assert rejected["ok"] is True
    assert rejected["status"] == "rejected"
    assert rejected["next_step"] == "status"

    _assert_redirect(client.get(GATE), STATUS_PAGE)
    _assert_redirect(client.get(DASHBOARD_PAGE), STATUS_PAGE)
    rejected_page = client.get(STATUS_PAGE)
    assert rejected_page.status_code == 200
    assert "تأیید نشد" in rejected_page.get_data(as_text=True)
    still_blocked = _body(client.post("/api/consultant/availability", json={"online": True}), 409)
    assert still_blocked["error"] == "not_approved"
    assert _body(client.get("/api/consultant/status"), 200)["status"] == "rejected"


def test_sales_coach_apply_link_follows_consultant_api_flag(app, client, monkeypatch):
    from app.express_partner.consultant_onboarding import consultant_api_enabled
    from app.express_partner.sales_coach import (
        build_home_ai_quick_prompts,
        build_limited_ai_quick_prompts,
    )

    monkeypatch.delenv("VINOR_CONSULTANT_API_ENABLED", raising=False)
    assert consultant_api_enabled() is True
    with app.test_request_context("/express/partner/home"):
        enabled = build_limited_ai_quick_prompts(me_phone=PHONE)
        enabled_home = build_home_ai_quick_prompts(me_phone=PHONE, is_approved=False)
    card = _apply_card(enabled)
    home_card = _apply_card(enabled_home)
    assert card["label"] == MARKETER_LABEL
    assert card["href"] == GATE
    assert home_card["label"] == MARKETER_LABEL
    assert home_card["href"] == GATE

    monkeypatch.setenv("VINOR_CONSULTANT_API_ENABLED", "0")
    assert consultant_api_enabled() is False
    with app.test_request_context("/express/partner/home"):
        disabled = build_limited_ai_quick_prompts(me_phone=PHONE)
        disabled_home = build_home_ai_quick_prompts(me_phone=PHONE, is_approved=False)
    legacy = _apply_card(disabled)
    legacy_home = _apply_card(disabled_home)
    assert legacy["label"] == LEGACY_LABEL
    assert legacy["href"] == OLD_APPLY_PAGE
    assert legacy_home["label"] == LEGACY_LABEL
    assert legacy_home["href"] == OLD_APPLY_PAGE
    _login(client)
    _assert_redirect(client.get(GATE), HOME_PAGE)


def _hub_apply_card(html: str) -> tuple[str, str]:
    match = re.search(
        r'<a class="vn-hub__hero" href="([^"]*)"[^>]*>\s*'
        r'<span class="vn-hub__hero-title">([^<]*)</span>',
        html,
    )
    assert match, "hub apply card missing"
    return match.group(1).replace("&amp;", "&"), match.group(2).strip()


def test_hub_apply_card_follows_consultant_api_flag(app, client, monkeypatch):
    """Hub hero uses the same consultant_api_enabled fallback as the coach link."""
    from app.express_partner.consultant_onboarding import consultant_api_enabled

    monkeypatch.delenv("VINOR_CONSULTANT_API_ENABLED", raising=False)
    assert consultant_api_enabled() is True
    _login(client)
    enabled = client.get(HOME_PAGE)
    assert enabled.status_code == 200, enabled.get_data(as_text=True)[:800]
    href, label = _hub_apply_card(enabled.get_data(as_text=True))
    assert label == MARKETER_LABEL
    assert href == GATE

    monkeypatch.setenv("VINOR_CONSULTANT_API_ENABLED", "0")
    assert consultant_api_enabled() is False
    disabled = client.get(HOME_PAGE)
    assert disabled.status_code == 200, disabled.get_data(as_text=True)[:800]
    href, label = _hub_apply_card(disabled.get_data(as_text=True))
    assert label == LEGACY_LABEL
    assert href == OLD_APPLY_PAGE
    assert GATE not in href
    assert "consultant" not in href
