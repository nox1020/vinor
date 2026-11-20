# -*- coding: utf-8 -*-
"""درخواست برداشت به سبک دیوار: مبلغ (چیپ و «همهٔ موجودی») → مقصد (شبای ذخیره‌شده یا جدید با چک‌سام)
→ تأیید → ثبت با کد پیگیری. رزرو مبلغ، آزاد شدن با لغو/رد، ضد دوبار ارسال، مالکیت، CSRF، دسترسی مالی
ادمین (fail-closed) و برچسب‌های بدون تکرار کیف پول. هیچ پول واقعی جابه‌جا نمی‌شود."""
from __future__ import annotations

import pytest

from test_owner_sold_hardening import (  # noqa: F401  (fixtures)
    MARKETER,
    OTHER,
    OWNER,
    _fund,
    _login,
    _partners,
    app,
    client,
)

API = "/express/partner/api/wallet/withdraw"
PAGE = "/express/partner/wallet/withdraw"
GOOD_SHEBA = "IR062960000000100324200001"
PARSIAN_SHEBA = "IR820540102680020817909002"
BAD_SHEBA = "IR062960000000100324200002"


@pytest.fixture(autouse=True)
def _quiet_sms(monkeypatch):
    monkeypatch.setattr("app.express_partner.routes._send_withdrawal_admin_sms", lambda **_k: None)
    monkeypatch.setattr("app.express_partner.commission_sms.notify_partner_commission_txn", lambda **_k: None)


def _hold(phone, amount, code="77"):
    from app.utils.storage import load_express_commissions, save_express_commissions

    rows = list(load_express_commissions() or [])
    rows.append({"id": 900 + len(rows), "commission_type": "escrow_hold", "partner_phone": phone,
                 "land_code": code, "commission_amount": amount, "status": "held",
                 "source": "sale_publish_escrow", "created_at": "2026-11-10T08:00:00Z"})
    save_express_commissions(rows)


def _withdrawals():
    from app.utils.storage import load_partner_withdrawals

    return list(load_partner_withdrawals() or [])


def _banks():
    from app.utils.storage import load_partner_bank_accounts

    return list(load_partner_bank_accounts() or [])


def _setup(client, amount=50_000_000, phone=OWNER):
    _partners()
    _fund(phone, amount)
    _login(client, phone)


def _submit(client, **body):
    resp = client.post(API, json=body)
    return resp.status_code, resp.get_json()


# ---------------------------------------------------------------- unit

def test_sheba_validation_and_bank_detection():
    from app.express_partner.withdraw_flow import bank_key_for_sheba, mask_sheba, validate_sheba

    assert validate_sheba(GOOD_SHEBA) == (GOOD_SHEBA, None)
    assert validate_sheba("06 2960 0000 0010 0324 2000 01") == (GOOD_SHEBA, None)
    assert validate_sheba("IR۰۶۲۹۶۰۰۰۰۰۰۰۱۰۰۳۲۴۲۰۰۰۰۱") == (GOOD_SHEBA, None)
    assert validate_sheba(BAD_SHEBA) == ("", "sheba_checksum")
    assert validate_sheba("IR1234") == ("", "sheba_format")
    assert validate_sheba("DE89370400440532013000") == ("", "sheba_format")
    assert bank_key_for_sheba(PARSIAN_SHEBA) == "parsian"
    assert bank_key_for_sheba(GOOD_SHEBA) == "other"
    assert mask_sheba(PARSIAN_SHEBA) == "IR82 •••• •••• 9002"


def test_bank_account_add_rejects_bad_sheba_checksum():
    from app.express_partner.partner_bank_accounts import normalize_sheba, validate_new_account

    assert normalize_sheba(BAD_SHEBA) == ""
    _rec, err = validate_new_account("mellat", "6037991234567890", "علی رضایی", BAD_SHEBA)
    assert err == "invalid_sheba"
    rec, err = validate_new_account("mellat", "6037991234567890", "علی رضایی", GOOD_SHEBA)
    assert err is None and rec["sheba"] == GOOD_SHEBA


def test_amount_chips_and_resolution():
    from app.express_partner.withdraw_flow import amount_chips, resolve_amount

    chips = amount_chips(35_000_000, 10_000_000)
    assert [c["amount"] for c in chips] == [10_000_000, 20_000_000, 35_000_000]
    assert chips[-1]["all"] and chips[-1]["key"] == "all"
    assert amount_chips(9_000_000, 10_000_000) == []
    assert resolve_amount(None, True, 35_000_000, 10_000_000) == (35_000_000, None)
    assert resolve_amount("۱۲٬۰۰۰٬۰۰۰", False, 35_000_000, 10_000_000) == (12_000_000, None)
    assert resolve_amount("5000000", False, 35_000_000, 10_000_000)[1] == "min_amount"
    assert resolve_amount("40000000", False, 35_000_000, 10_000_000)[1] == "insufficient_balance"
    assert resolve_amount("-5", False, 35_000_000, 10_000_000)[1] == "invalid_amount"
    assert resolve_amount("abc", False, 35_000_000, 10_000_000)[1] == "invalid_amount"


# ---------------------------------------------------------------- options

def test_options_available_excludes_blocked_and_pending(client):
    _setup(client, 60_000_000)
    _hold(OWNER, 15_000_000)
    code, body = _submit(client, amount=10_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    assert code == 200, body
    opts = client.get(API).get_json()
    assert opts["ok"] and opts["flow_version"] == 1 and opts["csrf_token"]
    assert opts["available"] == 35_000_000  # 60 − 15 بلوکه − 10 در انتظار
    assert opts["blocked"] == 15_000_000 and opts["pending_withdrawal"] == 10_000_000
    assert opts["chips"][-1] == {"key": "all", "amount": 35_000_000, "label": "همهٔ موجودی",
                                 "sub": "۳۵٬۰۰۰٬۰۰۰ تومان", "all": True}
    keys = {n["key"] for n in opts["notes"]}
    assert keys == {"blocked", "pending"}
    assert opts["texts"]["amount_question"] == "چقدر می‌خواهید برداشت کنید؟"
    assert opts["destinations"][0]["sheba_masked"] == "IR06 •••• •••• 0001"
    assert GOOD_SHEBA not in str(opts)  # شبای کامل به کلاینت همکار نمی‌رود
    assert opts["requests"][0]["status"] == "pending" and opts["requests"][0]["tracking_code"].startswith("W-")


def test_card_only_account_is_not_a_destination(client):
    from app.utils.storage import save_partner_bank_accounts

    _setup(client)
    save_partner_bank_accounts([{"id": "card1", "phone": OWNER, "bank_key": "mellat", "bank_name": "بانک ملت",
                                 "holder_name": "علی", "pan_prefix4": "6104", "pan_last4": "1234", "sheba": ""}])
    assert client.get(API).get_json()["destinations"] == []
    code, body = _submit(client, amount=10_000_000, account_id="card1")
    assert code == 400 and body["error"] == "sheba_required"


# ---------------------------------------------------------------- submit

def test_new_sheba_creates_account_and_reserves_amount(client):
    _setup(client, 50_000_000)
    code, body = _submit(client, amount=20_000_000, sheba=PARSIAN_SHEBA, holder_name="  علی   رضایی ",
                         client_request_id="req-1")
    assert code == 200 and body["ok"]
    req = body["request"]
    assert req["status"] == "pending" and req["status_label"] == "در انتظار بررسی"
    assert req["tracking_code"] == "W-" + req["id"][:8].upper()
    assert req["destination"] == "بانک پارسیان · IR82 •••• •••• 9002"
    assert body["available"] == 30_000_000
    banks = _banks()
    assert len(banks) == 1 and banks[0]["sheba"] == PARSIAN_SHEBA and banks[0]["holder_name"] == "علی رضایی"
    assert banks[0]["bank_key"] == "parsian" and banks[0]["is_default"] is True
    rows = _withdrawals()
    assert len(rows) == 1 and rows[0]["sheba"] == PARSIAN_SHEBA and rows[0]["bank_account_id"] == banks[0]["id"]
    assert client.get(API).get_json()["available"] == 30_000_000
    # همان شبا دوباره → حساب تکراری ساخته نمی‌شود
    code, _ = _submit(client, amount=10_000_000, sheba=PARSIAN_SHEBA, holder_name="علی رضایی")
    assert code == 200 and len(_banks()) == 1


def test_take_all_uses_server_balance_and_blocked_is_never_withdrawable(client):
    _setup(client, 50_000_000)
    _hold(OWNER, 20_000_000)
    code, body = _submit(client, amount=50_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    assert code == 400 and body["error"] == "insufficient_balance"
    code, body = _submit(client, all=True, amount=999_999_999, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    assert code == 200 and body["request"]["amount"] == 30_000_000 and body["available"] == 0
    code, body = _submit(client, all=True, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    assert code == 400 and body["error"] == "min_amount"


def test_double_submit_is_idempotent_and_no_double_spend(client):
    _setup(client, 30_000_000)
    first = _submit(client, amount=30_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی", client_request_id="dup")
    again = _submit(client, amount=30_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی", client_request_id="dup")
    assert first[0] == again[0] == 200 and again[1]["duplicate"] is True
    assert again[1]["request"]["id"] == first[1]["request"]["id"]
    assert len(_withdrawals()) == 1
    code, body = _submit(client, amount=30_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی", client_request_id="new")
    assert code == 400 and body["error"] == "insufficient_balance" and len(_withdrawals()) == 1


@pytest.mark.parametrize("payload,err", [
    ({"amount": 5_000_000, "sheba": GOOD_SHEBA, "holder_name": "علی"}, "min_amount"),
    ({"amount": 10_000_000}, "missing_bank"),
    ({"amount": 10_000_000, "sheba": BAD_SHEBA, "holder_name": "علی رضایی"}, "sheba_checksum"),
    ({"amount": 10_000_000, "sheba": "IR12", "holder_name": "علی رضایی"}, "sheba_format"),
    ({"amount": 10_000_000, "sheba": GOOD_SHEBA, "holder_name": "ع"}, "invalid_holder"),
    ({"amount": 10_000_000, "sheba": GOOD_SHEBA, "holder_name": "<script>"}, "invalid_holder"),
    ({"amount": 10_000_000, "sheba": GOOD_SHEBA, "holder_name": "علی", "client_request_id": "x" * 129},
     "invalid_request_id"),
])
def test_validation_errors_have_persian_messages(client, payload, err):
    _setup(client)
    code, body = _submit(client, **payload)
    assert code == 400 and body["error"] == err and body["message"]
    assert _withdrawals() == [] and _banks() == []


def test_ownership_other_partner_account_and_pages(client):
    from app.utils.storage import save_partner_bank_accounts

    _setup(client, 50_000_000, phone=OTHER)
    save_partner_bank_accounts([{"id": "theirs", "phone": OTHER, "bank_key": "other", "bank_name": "بانک",
                                 "holder_name": "دیگری", "pan_prefix4": "", "pan_last4": "", "sheba": GOOD_SHEBA}])
    code, body = _submit(client, amount=10_000_000, account_id="theirs")
    assert code == 200
    wid = body["request"]["id"]
    _fund(OWNER, 50_000_000)
    _login(client, OWNER)
    code, body = _submit(client, amount=10_000_000, account_id="theirs")
    assert code == 400 and body["error"] == "invalid_bank"
    assert client.get(API).get_json()["destinations"] == []
    assert client.get(f"{PAGE}/done/{wid}").status_code == 404
    resp = client.post(f"/express/partner/withdrawals/{wid}/cancel", json={})
    assert resp.status_code == 404
    assert _withdrawals()[0]["status"] == "pending"


def test_cancel_and_admin_reject_release_reservation(client, app, monkeypatch):
    _setup(client, 40_000_000)
    _, a = _submit(client, amount=10_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    _, b = _submit(client, amount=10_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    assert client.get(API).get_json()["available"] == 20_000_000
    resp = client.post(f"{PAGE}/{a['request']['id']}/cancel")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/express/partner/wallet")
    assert client.get(API).get_json()["available"] == 30_000_000
    resp = client.post(f"{PAGE}/{a['request']['id']}/cancel")  # دوباره → قابل لغو نیست
    assert resp.status_code == 302
    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: True)
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    resp = client.post(f"/admin/financial/withdrawals/{b['request']['id']}/status",
                       data={"status": "rejected", "admin_note": "شبا با نام یکی نیست"})
    assert resp.status_code == 302
    opts = client.get(API).get_json()
    assert opts["available"] == 40_000_000
    rejected = [r for r in opts["requests"] if r["status"] == "rejected"]
    assert rejected and rejected[0]["admin_note"] == "شبا با نام یکی نیست" and rejected[0]["tone"] == "red"


def test_admin_list_requires_finance_permission_fail_closed(client, monkeypatch):
    _setup(client, 40_000_000)
    _, body = _submit(client, amount=10_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: False)
    resp = client.get("/admin/financial/withdrawals")
    assert resp.status_code == 302 and GOOD_SHEBA not in resp.get_data(as_text=True)

    def _boom(*_a, **_k):
        raise RuntimeError("rbac down")

    monkeypatch.setattr("app.hardening.permissions.has_permission", _boom)
    assert client.get("/admin/financial/withdrawals").status_code == 403
    monkeypatch.setattr("app.hardening.permissions.has_permission", lambda *_a, **_k: True)
    html = client.get("/admin/financial/withdrawals").get_data(as_text=True)
    assert GOOD_SHEBA in html and body["request"]["tracking_code"] in html


def test_unapproved_or_anonymous_cannot_withdraw(client):
    from app.utils.storage import save_express_partners

    save_express_partners([{"phone": OWNER, "name": "مالک", "status": "pending"}])
    _fund(OWNER, 50_000_000)
    resp = client.post(API, json={"amount": 10_000_000, "sheba": GOOD_SHEBA, "holder_name": "علی رضایی"})
    assert resp.status_code in (401, 403)
    _login(client, OWNER)
    resp = client.post(API, json={"amount": 10_000_000, "sheba": GOOD_SHEBA, "holder_name": "علی رضایی"})
    assert resp.status_code in (401, 403) and _withdrawals() == []


def test_form_post_requires_csrf(app, client):
    app.config.update(WTF_CSRF_ENABLED=True)
    _setup(client, 40_000_000)
    resp = client.post(PAGE, data={"amount": "10000000", "sheba": GOOD_SHEBA, "holder_name": "علی رضایی",
                                   "client_request_id": "c1"})
    assert resp.status_code in (302, 400) and _withdrawals() == []
    resp = client.post(API, json={"amount": 10_000_000, "sheba": GOOD_SHEBA, "holder_name": "علی رضایی"})
    body = resp.get_json()
    assert resp.status_code == 400 and body["error"] == "csrf_expired" and body["csrf_token"]
    assert _withdrawals() == []
    resp = client.post(API, data="amount=10000000", content_type="text/plain")
    assert resp.status_code == 415 and _withdrawals() == []
    token_api = client.get(API).get_json()["csrf_token"]
    resp = client.post(API, json={"amount": 10_000_000, "sheba": GOOD_SHEBA, "holder_name": "علی رضایی",
                                  "client_request_id": "apk-1"}, headers={"X-CSRFToken": token_api})
    assert resp.status_code == 200 and len(_withdrawals()) == 1
    page = client.get(PAGE).get_data(as_text=True)
    import re

    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    rid = re.search(r'name="client_request_id" value="([^"]+)"', page).group(1)
    form = {"csrf_token": token, "client_request_id": rid, "amount": "10000000",
            "sheba": GOOD_SHEBA, "holder_name": "علی رضایی"}
    resp = client.post(PAGE, data=form)
    assert resp.status_code == 302 and "/wallet/withdraw/done/" in resp.headers["Location"]
    again = client.post(PAGE, data=form)  # دوبار زدن دکمه → همان درخواست
    assert again.headers["Location"] == resp.headers["Location"] and len(_withdrawals()) == 2
    done = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "درخواست برداشت ثبت شد" in done and "در انتظار بررسی" in done and "W-" in done


def test_form_error_redirects_back_with_message(client):
    _setup(client, 40_000_000)
    resp = client.post(PAGE, data={"amount": "10000000", "sheba": BAD_SHEBA, "holder_name": "علی رضایی"})
    assert resp.status_code == 302 and "error=sheba_checksum" in resp.headers["Location"]
    html = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "این شمارهٔ شبا معتبر نیست" in html


# ---------------------------------------------------------------- pages and labels

def test_wizard_page_steps_and_below_min(client):
    _setup(client, 40_000_000)
    html = client.get(PAGE).get_data(as_text=True)
    for step in ("amount", "dest", "summary"):
        assert f'data-ww-step="{step}"' in html
    assert "چقدر می‌خواهید برداشت کنید؟" in html and "به کدام حساب واریز شود؟" in html
    assert 'data-ww-chip="all"' in html and "همهٔ موجودی" in html and "مرحلهٔ ۱ از ۳" in html
    _partners()
    _login(client, MARKETER)
    _fund(MARKETER, 2_000_000)
    html = client.get(PAGE).get_data(as_text=True)
    assert 'data-ww-step="below_min"' in html and 'data-ww-step="amount"' not in html
    assert "فعلاً موجودی کافی برای برداشت ندارید" in html


def test_wallet_home_redesign_lists_requests_and_each_balance_once(client):
    _setup(client, 60_000_000)
    _hold(OWNER, 5_000_000)
    _submit(client, amount=10_000_000, sheba=GOOD_SHEBA, holder_name="علی رضایی")
    html = client.get("/express/partner/wallet").get_data(as_text=True)
    assert 'data-wallet-style="v2"' in html
    assert html.count("موجودی قابل استفاده") == 1
    assert html.count(">بلوکه برای پورسانت") <= 1 and 'data-wallet-line="blocked"' in html
    assert 'data-wallet-line="pending_withdrawal"' in html and "در انتظار برداشت" in html
    assert "کل موجودی" not in html and "کل درآمد" not in html
    assert "۴۵٬۰۰۰٬۰۰۰ تومان" in html  # 60 − 5 − 10
    assert 'data-wallet-request="pending"' in html and "data-wallet-request-cancel" in html
    assert 'data-wallet-topup' in html and 'href="/express/partner/wallet/withdraw"' in html
    api = client.get("/express/partner/api/wallet").get_json()
    assert [l["key"] for l in api["wallet"]["lines"]] == ["blocked", "pending_withdrawal"]
    assert api["withdraw"]["can_withdraw"] is True and api["withdraw"]["requests"][0]["status"] == "pending"


def test_commissions_labels_and_earned_excludes_topups(client):
    from app.utils.storage import load_express_commissions, save_express_commissions

    _setup(client, 40_000_000)  # شارژ/تعدیل: درآمد نیست
    rows = list(load_express_commissions() or [])
    rows.append({"id": 500, "commission_type": "deal", "partner_phone": OWNER, "land_code": "9",
                 "commission_amount": 3_000_000, "status": "approved"})
    rows.append({"id": 501, "commission_type": "manual_adjustment", "partner_phone": OWNER, "land_code": "9",
                 "commission_amount": -1_000_000, "status": "approved", "source": "deal_commission_payout"})
    save_express_commissions(rows)
    _hold(OWNER, 2_000_000)
    data = client.get("/express/partner/commissions/data").get_json()
    assert data["earned_commission"] == 3_000_000 and data["total_commission"] == 3_000_000
    assert data["sold_count"] == 1
    assert data["wallet_available"] == 40_000_000  # 40 + 3 − 1 − 2 بلوکه
    html = client.get("/express/partner/commissions").get_data(as_text=True)
    assert "کل موجودی" not in html and "کل درآمد" not in html
    assert "موجودی قابل استفاده" in html and "پورسانت کسب‌شده" in html and "در انتظار برداشت" in html
    assert 'href="/express/partner/wallet/withdraw"' in html
    snap = client.get("/express/partner/commissions/summary").get_json()["snapshot"]
    assert snap["wallet_available"] == 40_000_000 and snap["wallet_blocked"] == 2_000_000
    assert snap["earned_commission_amount"] == 3_000_000 and snap["can_withdraw"] is True


def test_bank_accounts_data_requestable_excludes_blocked(client):
    _setup(client, 30_000_000)
    _hold(OWNER, 25_000_000)
    body = client.get("/express/partner/bank-accounts/data").get_json()
    assert body["withdrawable_balance"] == 30_000_000 and body["requestable_balance"] == 5_000_000


def test_legacy_withdraw_endpoint_still_works(client):
    from app.utils.storage import save_partner_bank_accounts

    _setup(client, 30_000_000)
    save_partner_bank_accounts([{"id": "acc", "phone": OWNER, "bank_key": "mellat", "bank_name": "بانک ملت",
                                 "holder_name": "علی", "pan_prefix4": "6104", "pan_last4": "1234", "sheba": ""}])
    resp = client.post("/express/partner/withdrawals/request",
                       json={"amount": 10_000_000, "bank_account_id": "acc", "client_request_id": "L1"})
    body = resp.get_json()
    assert resp.status_code == 200 and body["request"]["bank_summary"] == "بانک ملت · 6104 **** **** 1234"
    again = client.post("/express/partner/withdrawals/request",
                        json={"amount": 10_000_000, "bank_account_id": "acc", "client_request_id": "L1"}).get_json()
    assert again["duplicate"] is True and len(_withdrawals()) == 1
