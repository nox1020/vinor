# -*- coding: utf-8 -*-
"""پنهان‌کردن کارت، قفل نتیجه بعد از معامله، و دیرکرد بدون حذف پورسانت."""
from __future__ import annotations

import pytest

OWNER = "09120000011"
MARKETER = "09120000022"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-followup-integrity")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, phone):
    with client.session_transaction() as sess:
        sess["user_phone"] = phone
        sess["logged_in"] = True


def _partners(app):
    from app.utils.storage import save_express_partners

    with app.app_context():
        save_express_partners([
            {"phone": OWNER, "status": "approved", "name": "مالک"},
            {"phone": MARKETER, "status": "approved", "name": "مشاور"},
        ])


def _visit(**extra):
    row = {
        "id": "v1",
        "partner_phone": MARKETER,
        "owner_phone": OWNER,
        "land_code": "9",
        "land_title": "فایل",
        "status": "completed",
        "visit_outcome": "interested",
    }
    row.update(extra)
    return row


def test_remove_hides_for_one_side_and_keeps_the_document(app, client):
    from app.express_partner.visit_requests import card_hidden_for
    from app.utils.storage import load_express_visit_requests, save_ads, save_express_visit_requests

    _partners(app)
    with app.app_context():
        save_ads([{"code": "9", "title": "فایل", "owner": OWNER, "public": True}])
        save_express_visit_requests([_visit(status="completed")])
    _login(client, MARKETER)
    resp = client.post("/express/partner/requests/v1/remove")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["action"] == "hidden"
    with app.app_context():
        rows = load_express_visit_requests()
    assert len(rows) == 1
    assert rows[0]["id"] == "v1"
    assert card_hidden_for(rows[0], MARKETER) is True
    assert card_hidden_for(rows[0], OWNER) is False


def test_protected_visit_is_not_popped(app):
    from app.express_partner.visit_requests import partner_delete_own_visit
    from app.utils.storage import save_express_commissions

    rows = [_visit(deal_decision="approved")]
    with app.app_context():
        save_express_commissions([{
            "id": 3,
            "commission_type": "deal",
            "partner_phone": MARKETER,
            "land_code": "9",
            "commission_amount": 1000,
            "status": "pending",
        }])
        ok, err = partner_delete_own_visit(rows, request_id="v1", partner_phone=MARKETER)
    assert ok is True and err is None
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"


def test_outcome_freezes_after_deal_confirm(app, client):
    from app.utils.storage import save_ads, save_express_assignments, save_express_visit_requests

    _partners(app)
    with app.app_context():
        save_ads([{"code": "9", "title": "فایل", "owner": OWNER}])
        save_express_assignments([{
            "id": 1,
            "land_code": "9",
            "partner_phone": MARKETER,
            "status": "in_transaction",
            "transaction_holder": MARKETER,
        }])
        save_express_visit_requests([_visit(deal_decision="approved")])
    _login(client, MARKETER)
    resp = client.post(
        "/express/partner/requests/v1/visit-result",
        json={"outcome": "not_interested"},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error_code"] == "outcome_frozen"


def test_legacy_deal_paths_refuse_the_marketer(app, client):
    from app.ai.agent_tools import _execute_release_deal, _execute_start_deal

    _partners(app)
    _login(client, MARKETER)
    resp = client.post(
        "/express/partner/mark-in-transaction/9",
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error_code"] == "owner_flow_required"
    started = _execute_start_deal(MARKETER, "9")
    released = _execute_release_deal(MARKETER, "9")
    assert started["error"] == "owner_flow_required"
    assert released["error"] == "owner_flow_required"


def test_overdue_keeps_pending_commission_and_lists_the_gap(app, client):
    from datetime import datetime, timedelta

    from app.express_partner.routes import _auto_release_expired_transactions
    from app.express_partner.special_visit_inbox import approved_deals_missing_pending
    from app.utils.storage import (
        load_express_assignments,
        load_express_commissions,
        save_express_assignments,
        save_express_commissions,
        save_express_visit_requests,
    )

    started = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")
    with app.app_context():
        save_express_assignments([{
            "id": 1,
            "land_code": "9",
            "partner_phone": MARKETER,
            "status": "in_transaction",
            "transaction_holder": MARKETER,
            "transaction_started_at": started,
        }])
        save_express_commissions([{
            "id": 4,
            "commission_type": "deal",
            "partner_phone": MARKETER,
            "land_code": "9",
            "commission_amount": 2000,
            "status": "pending",
        }])
        save_express_visit_requests([_visit(id="gap", land_code="8", deal_decision="approved")])
        _auto_release_expired_transactions([])
        assignment = load_express_assignments()[0]
        commission = load_express_commissions()[0]
        missing = approved_deals_missing_pending()
    assert assignment["status"] == "in_transaction"
    assert assignment["deal_overdue"] is True
    assert commission["status"] == "pending"
    assert missing[0]["visit_id"] == "gap"
    _login(client, OWNER)
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    page = client.get("/admin/express/deals/missing-pending")
    assert page.status_code == 200
    assert "gap" in page.get_data(as_text=True)
    overdue = client.get("/admin/express/deals/overdue")
    assert overdue.status_code == 200
    assert "9" in overdue.get_data(as_text=True)


def test_owner_result_is_rejected_and_archive_is_per_actor(app, client):
    from app.express_partner.visit_requests import card_archived_for
    from app.utils.storage import load_express_visit_requests, save_ads, save_express_visit_requests

    _partners(app)
    with app.app_context():
        save_ads([{"code": "9", "title": "فایل", "owner": OWNER, "public": True, "is_express": True}])
        save_express_visit_requests([_visit(status="completed")])
    _login(client, OWNER)
    result = client.post(
        "/express/partner/inbox-visits/v1/result",
        data={"outcome": "follow_up"},
        headers={"Accept": "application/json"},
    )
    assert result.status_code == 403
    with app.app_context():
        save_express_visit_requests([_visit(status="done_pending")])
    _login(client, OWNER)
    denied = client.post("/express/partner/inbox-visits/v1/no_show", data={"notes": "نبود"})
    assert denied.status_code == 302
    with app.app_context():
        row = load_express_visit_requests()[0]
    assert row["status"] == "disputed"
    assert row["status"] != "no_show"
    archived = client.post("/express/partner/api/requests/v1/archive", json={})
    assert archived.status_code == 200
    assert archived.get_json()["archived"] is True
    with app.app_context():
        stored = load_express_visit_requests()[0]
    assert card_archived_for(stored, OWNER) is True
    assert card_archived_for(stored, MARKETER) is False
