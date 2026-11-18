# -*- coding: utf-8 -*-
"""سخت‌سازی «فروخته شد» مالک: H1 (همهٔ وضعیت‌های بازدید)، M1 (قفل پورسانت)، M2 (بازگردانی
فروخته‌شده)، L1 (CSRF فرم)، L2 (دسترسی مالی ادمین)، L3 (پروندهٔ بدون بلوکه)، L4 (تلاش دوباره)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

OWNER = "09120000000"
MARKETER = "09123333333"
OTHER = "09122222222"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-owner-sold-hardening")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_ENABLED", "0")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setattr(
        "app.express_partner.new_land_sms.notify_all_partners_new_express_land_background",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr("app.express_partner.special_visit_inbox.inject_visit_deal_chat", lambda *_a, **_k: None)
    monkeypatch.setattr("app.express_partner.special_visit_inbox._notify_started_deal", lambda *_a, **_k: None)
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


def _partners():
    from app.utils.storage import save_express_partners

    save_express_partners([
        {"phone": OWNER, "name": "مالک", "status": "approved", "total_income": 0},
        {"phone": MARKETER, "name": "بازاریاب", "status": "approved", "total_income": 0},
        {"phone": OTHER, "name": "دیگری", "status": "approved", "total_income": 0},
    ])


def _fund(phone=OWNER, amount=500_000_000):
    from app.utils.storage import load_express_commissions, save_express_commissions

    funded = list(load_express_commissions() or [])
    funded.append({
        "id": len(funded) + 1, "commission_type": "manual_adjustment", "partner_phone": phone,
        "land_code": "manual", "commission_amount": amount, "status": "approved", "source": "test_fund",
    })
    save_express_commissions(funded)


def _publish(phone=OWNER):
    from app.listings.service import create_listing, publish_listing

    _partners()
    created = create_listing({"title": "ملک فروشی", "city": "کرج", "price_total": 2_000_000_000}, owner=phone)
    code = str(created["code"])
    _fund(phone)
    _published, err, changed = publish_listing(phone, payment_method="نقدی", commission_pct=2, land_code=code)
    assert err is None and changed
    return code


def _visit(code, status, *, partner=MARKETER, past=False, **extra):
    from app.express_partner.visit_requests import create_visit_request
    from app.utils.storage import load_express_visit_requests, save_express_visit_requests

    rows = list(load_express_visit_requests() or [])
    day = date.today() + timedelta(days=1)
    for _ in range(30):
        rec, _err = create_visit_request(
            rows, partner_phone=partner, partner_name="بازاریاب", land_code=code,
            land_title="ملک فروشی", visit_date=day.isoformat(), customer_first_name="علی",
            customer_last_name="رضایی", customer_phone="09120000099",
        )
        if rec:
            rec["status"] = status
            if past:
                rec["visit_date"] = (date.today() - timedelta(days=3)).isoformat()
            rec.update(extra)
            save_express_visit_requests(rows)
            return rec
        day += timedelta(days=1)
    raise AssertionError("no visit slot")


def _hold(code):
    from app.utils.storage import load_express_commissions

    rows = [r for r in load_express_commissions() or []
            if r.get("commission_type") == "escrow_hold" and str(r.get("land_code")) == str(code)]
    return rows[-1] if rows else None


def _sell_outside(client, code):
    resp = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "outside"})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


# ---------------------------------------------------------------- H1
@pytest.mark.parametrize("status,kwargs,listed", [
    ("done_pending", {}, True),
    ("disputed", {"dispute_reason": "بازدید انجام نشد"}, False),
    ("no_show", {"dispute_reason": "مشتری آمد ولی ثبت نشد"}, False),
    ("approved", {"past": True}, False),
])
def test_h1_any_marketer_visit_state_sends_outside_sale_to_review(client, app, status, kwargs, listed):
    with app.app_context():
        code = _publish()
        visit = _visit(code, status, **kwargs)
    _login(client, OWNER)
    opts = client.get(f"/express/partner/api/my-property/sold-options?code={code}").get_json()
    assert opts["review_required_if_outside"] is True
    assert opts["review_warning"]
    assert ([v["visit_id"] for v in opts["visits"]] == [visit["id"]]) is listed
    body = _sell_outside(client, code)
    assert body["review_required"] is True and body["hold_released"] is False
    with app.app_context():
        hold = _hold(code)
        assert hold["status"] == "held" and hold["review_required"] is True
        assert hold["review_visit_ids"] == [visit["id"]]


@pytest.mark.parametrize("status,kwargs", [
    ("approved", {}),           # future slot: visit hasn't happened yet
    ("no_show", {}),            # plain no-show, no dispute
    ("cancelled", {}),
    ("pending", {}),
])
def test_h1_harmless_visit_states_still_release(client, app, status, kwargs):
    with app.app_context():
        code = _publish()
        _visit(code, status, **kwargs)
    _login(client, OWNER)
    body = _sell_outside(client, code)
    assert body["review_required"] is False and body["hold_released"] is True
    with app.app_context():
        assert _hold(code)["status"] == "released"


def test_h1_sell_via_done_pending_visit_confirms_attendance_and_pays(client, app):
    with app.app_context():
        code = _publish()
        visit = _visit(code, "done_pending")
        from app.utils.storage import save_express_assignments
        save_express_assignments([{"land_code": code, "partner_phone": MARKETER, "status": "active"}])
    _login(client, OWNER)
    resp = client.post("/express/partner/api/my-property/sold",
                       json={"code": code, "channel": "vinor", "visit_id": visit["id"]})
    assert resp.status_code == 200, resp.get_json()
    with app.app_context():
        from app.utils.storage import load_express_commissions, load_express_visit_requests

        row = next(r for r in load_express_visit_requests() if r.get("id") == visit["id"])
        assert row["status"] == "completed" and row.get("deal_decision") == "closed"
        deals = [r for r in load_express_commissions() if r.get("commission_type") == "deal"]
        assert len(deals) == 1 and deals[0]["status"] == "approved"
        assert _hold(code)["status"] == "settled"


def test_h1_disputed_visit_is_not_a_via_vinor_choice(client, app):
    with app.app_context():
        code = _publish()
        visit = _visit(code, "disputed", dispute_reason="انجام نشد")
    _login(client, OWNER)
    resp = client.post("/express/partner/api/my-property/sold",
                       json={"code": code, "channel": "vinor", "visit_id": visit["id"]})
    assert resp.status_code == 404 and resp.get_json()["error_code"] == "visit_not_found"


def test_h1_admin_page_shows_new_states_and_starts_deal(client, app):
    with app.app_context():
        code = _publish()
        visit = _visit(code, "done_pending")
        from app.utils.storage import save_express_assignments
        save_express_assignments([{"land_code": code, "partner_phone": MARKETER, "status": "active"}])
    _login(client, OWNER)
    _sell_outside(client, code)
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    html = client.get("/admin/express/commissions/escrow-review").get_data(as_text=True)
    assert code in html and "منتظر تأیید مالک" in html and visit["id"] in html
    resp = client.post(f"/admin/express/commissions/escrow-review/{code}/deal", data={"visit_id": visit["id"]})
    assert resp.status_code == 302
    with app.app_context():
        from app.utils.storage import load_express_commissions

        deals = [r for r in load_express_commissions() if r.get("commission_type") == "deal"]
        assert len(deals) == 1 and deals[0]["partner_phone"] == MARKETER
        assert _hold(code)["review_resolution"] == "deal_started"


# ---------------------------------------------------------------- M1
def test_m1_ensure_hold_refuses_amount_change_under_review():
    from app.express_partner.commission_escrow import ensure_hold

    commissions = [
        {"id": 1, "commission_type": "manual_adjustment", "partner_phone": OWNER, "land_code": "manual",
         "commission_amount": 900, "status": "approved"},
        {"id": 2, "commission_type": "escrow_hold", "partner_phone": OWNER, "land_code": "7",
         "commission_amount": 100, "status": "held", "review_required": True},
    ]
    for amount in (0, 50, 200):
        err, detail = ensure_hold(commissions, [], phone=OWNER, land_code="7", amount=amount)
        assert err == "review_locked" and "بررسی" in detail["message"]
    assert commissions[1]["status"] == "held" and commissions[1]["commission_amount"] == 100
    err, _ = ensure_hold(commissions, [], phone=OWNER, land_code="7", amount=100)
    assert err is None


def _special_form(code="", pct="2", price="2000000000", update=False):
    from app.express_partner.special_listings import form_from_mapping

    data = {
        "title": "زمین فروشی کرج شمالی", "location": "کرج", "city": "کرج", "size": "500",
        "price_total": price, "payment_method": "نقدی", "express_commission_pct": pct,
    }
    if update:
        data.update({"update_existing": "1", "code": code})
    return form_from_mapping(data)


def _special_listing():
    from app.express_partner.special_listings import create_special_listing_from_express_form, empty_upload_files

    _partners()
    _fund()
    rec, err = create_special_listing_from_express_form(
        owner_phone=OWNER, form=_special_form(), files=empty_upload_files(), cities=None,
    )
    assert err is None, err
    return str(rec["code"])


def _edit(code, **kw):
    from app.express_partner.special_listings import create_special_listing_from_express_form, empty_upload_files

    return create_special_listing_from_express_form(
        owner_phone=OWNER, form=_special_form(code, update=True, **kw), files=empty_upload_files(), cities=None,
    )


def test_m1_edit_cannot_shrink_hold_under_review(client, app):
    with app.app_context():
        code = _special_listing()
        held = int(_hold(code)["commission_amount"])
        assert held > 0
        _visit(code, "done_pending")
    _login(client, OWNER)
    with app.app_context():
        from app.express_partner.commission_escrow import flag_hold_for_review
        flag_hold_for_review(code, reason="test")
        rec, err = _edit(code, pct="0.1")
        assert err == "review_locked" and rec is None
        hold = _hold(code)
        assert hold["status"] == "held" and int(hold["commission_amount"]) == held


def test_m1_lowering_commission_after_visit_is_blocked_raising_is_allowed(app):
    from app.express_partner.special_listings import SPECIAL_LISTING_ERRORS

    with app.app_context():
        code = _special_listing()
        held = int(_hold(code)["commission_amount"])
        _visit(code, "approved", past=True)
        rec, err = _edit(code, pct="1")
        assert err == "commission_locked" and "بازدید" in SPECIAL_LISTING_ERRORS[err]
        rec, err = _edit(code, price="1000000000")  # cheaper price shrinks the commission too
        assert err == "commission_locked"
        assert int(_hold(code)["commission_amount"]) == held
        rec, err = _edit(code, pct="3")
        assert err is None and int(_hold(code)["commission_amount"]) > held


def test_m1_lowering_without_visits_still_works(app):
    with app.app_context():
        code = _special_listing()
        held = int(_hold(code)["commission_amount"])
        rec, err = _edit(code, pct="1")
        assert err is None and int(_hold(code)["commission_amount"]) < held


def test_m1_sold_listing_cannot_be_edited(client, app):
    with app.app_context():
        code = _special_listing()
    _login(client, OWNER)
    _sell_outside(client, code)
    with app.app_context():
        rec, err = _edit(code, pct="2")
        assert err == "listing_sold"


# ---------------------------------------------------------------- M2
def test_m2_sold_listing_cannot_be_restored_and_button_hidden(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    _sell_outside(client, code)
    with app.app_context():
        assert _hold(code)["status"] == "released"
    resp = client.post("/express/partner/api/my-property/restore", json={"code": code})
    body = resp.get_json()
    assert resp.status_code == 409 and body["error_code"] == "sold_locked" and body["can_restore"] is False
    with app.app_context():
        from app.listings.service import get_listing, restore_listing
        from app.utils.storage import load_express_commissions

        land = get_listing(code)
        assert land["express_status"] == "sold" and land.get("archived")
        assert len([r for r in load_express_commissions() if r.get("commission_type") == "escrow_hold"]) == 1
        assert _hold(code)["status"] == "released"
        _land, err, changed = restore_listing(code, require_owner=False)
        assert err == "sold_locked" and changed is False
    data = client.get("/express/partner/api/my-property/data?status=archived").get_json()
    card = next(i for i in data["items"] if str(i["code"]) == code)
    assert card["can_restore"] is False and card["sold"] is True
    html = client.get("/express/partner/my-property?status=archived").get_data(as_text=True)
    assert "فروخته‌شده" in html and "بازگرداندن به فعال" not in html


def test_m2_plain_archived_listing_still_restorable(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    assert client.post("/express/partner/api/my-property/archive", json={"code": code}).status_code == 200
    data = client.get("/express/partner/api/my-property/data?status=archived").get_json()
    card = next(i for i in data["items"] if str(i["code"]) == code)
    assert card["can_restore"] is True
    html = client.get("/express/partner/my-property?status=archived").get_data(as_text=True)
    assert "بازگرداندن به فعال" in html
    resp = client.post("/express/partner/api/my-property/restore", json={"code": code})
    assert resp.status_code == 200, resp.get_json()


# ---------------------------------------------------------------- L1
def test_l1_form_post_requires_csrf_but_json_does_not(client, app):
    with app.app_context():
        code = _publish()
        other = _publish()
    _login(client, OWNER)
    resp = client.post("/express/partner/api/my-property/sold",
                       data={"code": code, "channel": "outside", "visit_id": ""})
    assert resp.status_code == 302
    resp = client.post("/express/partner/api/my-property/sold",
                       data={"code": code, "channel": "outside", "csrf_token": "forged"})
    assert resp.status_code == 302
    with app.app_context():
        from app.listings.service import get_listing
        assert get_listing(code).get("express_status") != "sold"
        assert _hold(code)["status"] == "held"

    # A non-browser form body (no flash/redirect path) gets JSON 400 csrf_failed.
    raw = client.post("/express/partner/api/my-property/sold", data="code=%s&channel=outside" % code,
                      content_type="text/plain")
    assert raw.status_code == 400 and raw.get_json()["error_code"] == "csrf_failed"

    page = client.get(f"/express/partner/my-property/{code}/sold").get_data(as_text=True)
    import re
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    resp = client.post("/express/partner/api/my-property/sold",
                       data={"code": code, "channel": "outside", "visit_id": "", "csrf_token": token})
    assert resp.status_code == 302
    with app.app_context():
        from app.listings.service import get_listing
        assert get_listing(code)["express_status"] == "sold"

    # APK path: JSON body, no CSRF token.
    ok = client.post("/express/partner/api/my-property/sold", json={"code": other, "channel": "outside"})
    assert ok.status_code == 200 and ok.get_json()["sold"] is True


def test_l5_web_submit_button_is_disabled_after_first_click(client, app):
    with app.app_context():
        code = _publish()
        _visit(code, "done_pending")
    _login(client, OWNER)
    html = client.get(f"/express/partner/my-property/{code}/sold").get_data(as_text=True)
    assert "data-owner-sold-submit" in html and "submitBtn.disabled = true" in html
    assert "data-owner-sold-review-warning" in html


# ---------------------------------------------------------------- L2
def test_l2_escrow_review_fails_closed(client, app, monkeypatch):
    with client.session_transaction() as sess:
        sess["logged_in"] = True

    def boom(*_a, **_k):
        raise RuntimeError("rbac down")

    monkeypatch.setattr("app.hardening.permissions.has_permission", boom)
    page = client.get("/admin/express/commissions/escrow-review")
    assert page.status_code in (302, 403)
    assert "بلوکه‌های در انتظار بازبینی" not in page.get_data(as_text=True)
    resp = client.post("/admin/express/commissions/escrow-review/1/release")
    assert resp.status_code in (302, 403)

    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: False)
    page = client.get("/admin/express/commissions/escrow-review")
    assert page.status_code in (302, 403)
    assert "بلوکه‌های در انتظار بازبینی" not in page.get_data(as_text=True)

    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: True)
    page = client.get("/admin/express/commissions/escrow-review")
    assert page.status_code == 200 and "بلوکه‌های در انتظار بازبینی" in page.get_data(as_text=True)


# ---------------------------------------------------------------- L3
def test_l3_legacy_listing_without_hold_still_opens_review_case(client, app):
    with app.app_context():
        code = _publish()
        visit = _visit(code, "completed")
        from app.express_partner.commission_escrow import release_publish_hold
        assert release_publish_hold(code, reason="legacy_test", force=True) is True
        assert _hold(code) is None or _hold(code)["status"] != "held"
    _login(client, OWNER)
    body = _sell_outside(client, code)
    assert body["review_required"] is True
    again = client.post("/express/partner/api/my-property/sold", json={"code": code, "channel": "outside"})
    assert again.get_json()["already"] is True
    with app.app_context():
        from app.express_partner.commission_escrow import open_review_cases

        cases = open_review_cases()
        assert [c["land_code"] for c in cases] == [code]
        assert cases[0]["review_visit_ids"] == [visit["id"]] and cases[0]["has_hold"] is False
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    html = client.get("/admin/express/commissions/escrow-review").get_data(as_text=True)
    assert f'data-review-case="{code}"' in html
    resp = client.post(f"/admin/express/commissions/escrow-review/{code}/release")
    assert resp.status_code == 302
    with app.app_context():
        from app.express_partner.commission_escrow import open_review_cases
        assert open_review_cases() == []


# ---------------------------------------------------------------- L4
def test_l4_close_failure_after_confirm_gives_retry_message_and_retry_works(client, app, monkeypatch):
    import app.express_partner.special_visit_inbox as inbox

    with app.app_context():
        code = _publish()
        visit = _visit(code, "completed")
        from app.utils.storage import save_express_assignments
        save_express_assignments([{"land_code": code, "partner_phone": MARKETER, "status": "active"}])
    real = inbox.commit_deal_after_listing

    def short_on_close(requests, rec, *, decision, **kw):
        if decision == "closed":
            return None, "wallet_insufficient"
        return real(requests, rec, decision=decision, **kw)

    monkeypatch.setattr(inbox, "commit_deal_after_listing", short_on_close)
    _login(client, OWNER)
    resp = client.post("/express/partner/api/my-property/sold",
                       json={"code": code, "channel": "vinor", "visit_id": visit["id"]})
    body = resp.get_json()
    assert resp.status_code == 400 and body["error_code"] == "wallet_insufficient"
    assert body["deal_started"] is True and "معامله با بازاریاب ثبت شد" in body["error"]
    assert "شارژ" in body["error"] and "دوباره" in body["error"]
    with app.app_context():
        from app.listings.service import get_listing
        from app.utils.storage import load_express_visit_requests

        assert get_listing(code).get("express_status") != "sold"
        row = next(r for r in load_express_visit_requests() if r.get("id") == visit["id"])
        assert row.get("deal_decision") == "approved"

    monkeypatch.setattr(inbox, "commit_deal_after_listing", real)
    opts = client.get(f"/express/partner/api/my-property/sold-options?code={code}").get_json()
    assert [v["visit_id"] for v in opts["visits"]] == [visit["id"]]
    retry = client.post("/express/partner/api/my-property/sold",
                        json={"code": code, "channel": "vinor", "visit_id": visit["id"]})
    assert retry.status_code == 200, retry.get_json()
    with app.app_context():
        from app.utils.storage import load_express_commissions

        deals = [r for r in load_express_commissions() if r.get("commission_type") == "deal"]
        assert len(deals) == 1 and deals[0]["status"] == "approved"
        assert _hold(code)["status"] == "settled"
