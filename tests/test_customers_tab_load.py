# -*- coding: utf-8 -*-
"""تب «مشتریان» باید مثل «خانه» و «پیگیری» سریع و سبک لود شود (وب + اپ)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PARTNER = "09121111111"
CRM_ENV = {
    "VINOR_CRM_ENABLED": "1",
    "VINOR_CRM_UI_ENABLED": "1",
    "VINOR_CRM_AI_TOOLS_ENABLED": "0",
    "VINOR_CRM_VISIT_SYNC_ENABLED": "0",
    "VINOR_CRM_ACTIVITY_HOOK_ENABLED": "0",
}


@pytest.fixture()
def crm_env():
    tmp = tempfile.mkdtemp()
    with mock.patch.dict(os.environ, dict(CRM_ENV, INSTANCE_PATH=tmp), clear=False):
        yield tmp


def _seed(n_contacts=4, calls_each=5):
    from app.crm.service import log_call, schedule_followup, upsert_contact

    ids = []
    for i in range(n_contacts):
        c = upsert_contact(
            partner_phone=PARTNER,
            customer_phone=f"0912200000{i}",
            first_name=f"نام{i}",
            last_name="تست",
            source="manual",
        )
        ids.append(c.id)
        for k in range(calls_each):
            log_call(partner_phone=PARTNER, contact_id=c.id, outcome="answered", notes=f"c{i}-{k}")
        schedule_followup(partner_phone=PARTNER, contact_id=c.id, due_at="2026-12-01", notes=f"f{i}")
    # مشتری همکار دیگر نباید نشت کند
    other = upsert_contact(partner_phone="09129999999", customer_phone="09125555555",
                           first_name="غریبه", last_name="x", source="manual")
    log_call(partner_phone="09129999999", contact_id=other.id, outcome="answered", notes="other")
    return ids


def test_view_reads_each_crm_file_once(crm_env):
    from app.crm import store
    from app.express_partner.customers import partner_customers_view

    _seed(n_contacts=6, calls_each=4)
    real = store._load_raw
    seen = []

    def spy(name, app=None):
        seen.append(name)
        return real(name, app)

    with mock.patch.object(store, "_load_raw", side_effect=spy):
        rows = partner_customers_view(PARTNER)
    assert len(rows) == 6
    # قبلاً 1 + 2N (اینجا ۱۳) بار؛ حالا هر فایل یک‌بار
    assert len(seen) == 3, seen
    assert sorted(set(seen)) == sorted(seen)


def test_view_groups_latest_three_per_contact(crm_env):
    from app.express_partner.customers import partner_customers_view

    ids = _seed(n_contacts=3, calls_each=5)
    rows = {r["id"]: r for r in partner_customers_view(PARTNER)}
    assert set(rows) == set(ids)
    for i, cid in enumerate(ids):
        notes = [c["notes"] for c in rows[cid]["recent_calls"]]
        assert notes == [f"c{i}-4", f"c{i}-3", f"c{i}-2"]  # جدیدترین اول، سقف ۳
        assert [f["notes"] for f in rows[cid]["pending_followups"]] == [f"f{i}"]
    assert all("other" not in str(r) for r in rows.values())


def _client(phone=None):
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    if phone:
        with client.session_transaction() as sess:
            sess["user_phone"] = phone
            sess["logged_in"] = True
            sess["VINOR_IS_EXPRESS_PARTNER"] = True
    return client


def _approved():
    return (
        mock.patch("app.express_partner.partner_roles.partner_is_approved", return_value=True),
        mock.patch("app.utils.storage.load_express_partners",
                   return_value=[{"phone": PARTNER, "status": "approved"}]),
    )


def test_apk_customers_data_json(crm_env):
    _seed(n_contacts=2, calls_each=1)
    client = _client(PARTNER)
    a, b = _approved()
    with a, b:
        resp = client.get("/express/partner/api/customers/data")
    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("Cache-Control", "")
    data = resp.get_json()
    assert data["ok"] is True
    assert data["csrf_token"]
    assert len(data["customers"]) == 2
    assert {f["name"] for f in data["fields"]} == {"first_name", "last_name", "customer_phone"}
    assert data["action_path"] == "/express/partner/customers"
    row = data["customers"][0]
    for key in ("id", "display_name", "customer_phone", "recent_calls", "pending_followups"):
        assert key in row


def test_apk_customers_data_guest_is_json_401(crm_env):
    resp = _client().get("/express/partner/api/customers/data")
    assert resp.status_code in (401, 403)
    assert resp.is_json


def test_apk_customers_data_disabled_flag(crm_env):
    client = _client(PARTNER)
    a, b = _approved()
    with a, b, mock.patch.dict(os.environ, {"VINOR_CRM_UI_ENABLED": "0"}, clear=False):
        resp = client.get("/express/partner/api/customers/data")
    assert resp.status_code == 404
    assert resp.is_json


def test_web_nav_treats_customers_like_other_tabs():
    src = (ROOT / "app" / "static" / "express-partner" / "express-nav.js").read_text(encoding="utf-8")
    registry = src.split("var ROUTE_REGISTRY = {", 1)[1].split("};", 1)[0]
    assert "'/express/partner/customers': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true }" in registry
    menu = src.split("var MAIN_MENU_PATHS = [", 1)[1].split("];", 1)[0]
    assert "'/express/partner/customers'" in menu
    login = src.split("function requiresLoginPath(pathname) {", 1)[1].split("}", 1)[0]
    assert "'/express/partner/customers'" in login
