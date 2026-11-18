# -*- coding: utf-8 -*-
"""شارژ کیف پول به سبک دیوار: پیش‌پر کردن کمبود با زمینهٔ امضاشده، فهرست مجاز مقصد بازگشت،
حالت‌های صفحهٔ نتیجه، و یک‌بار واریز برای هر authority. درگاه زرین‌پال همه‌جا ساختگی است."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

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

CHARGE = "/express/partner/wallet/charge"
CALLBACK = "/express/partner/wallet/zarinpal/callback"


@pytest.fixture
def gateway(monkeypatch):
    """درگاه ساختگی: authority پشت سر هم، verify قابل تنظیم، بدون هیچ درخواست شبکه."""
    state = {"n": 0, "requests": [], "verify": {"ok": True, "ref_id": "REF-1"}, "verify_calls": []}
    mod = "app.express_partner.wallet_topup"

    def _request(**kw):
        state["n"] += 1
        state["requests"].append(kw)
        return {"ok": True, "authority": f"A{state['n']:04d}"}

    def _verify(**kw):
        state["verify_calls"].append(kw)
        return dict(state["verify"])

    monkeypatch.setattr(f"{mod}.payment_flow_active", lambda: True)
    monkeypatch.setattr(f"{mod}.get_zarinpal_settings", lambda: {"sandbox": True})
    monkeypatch.setattr(f"{mod}.effective_merchant_id", lambda _c=None: "merchant")
    monkeypatch.setattr(f"{mod}.payment_request", _request)
    monkeypatch.setattr(f"{mod}.payment_verify", _verify)
    monkeypatch.setattr(f"{mod}.start_pay_url", lambda a, sandbox=False: f"https://sandbox.zarinpal.com/pg/StartPay/{a}")
    return state


def _rows():
    from app.utils.storage import load_express_commissions

    return [r for r in load_express_commissions() or [] if r.get("source") == "wallet_zarinpal"]


def _ctx(app, phone=OWNER, shortfall=2_000_000, reason="publish", code="123"):
    from app.express_partner.wallet_charge_flow import make_context

    with app.test_request_context():
        return make_context(phone=phone, shortfall=shortfall, reason=reason, code=code)


def _api(client, **params):
    return client.get("/express/partner/api/wallet", query_string=params).get_json()


def _start(client, amount=500_000, **extra):
    resp = client.post(CHARGE, json={"amount": amount, **extra})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _result_url(resp):
    assert resp.status_code == 302
    return resp.headers["Location"]


# ------------------------------------------------------------- shortfall prefill / validation

def test_signed_shortfall_prefills_and_explains(client, app):
    _partners()
    _login(client, OWNER)
    body = _api(client, ctx=_ctx(app))
    assert body["ok"] and body["flow_version"] == 1
    assert body["prefill"] == 2_000_000 and body["shortfall"] == 2_000_000
    assert body["reason_line"] == "برای انتشار این آگهی ۲٬۰۰۰٬۰۰۰ تومان کم دارید."
    assert body["presets"][0]["amount"] == 2_000_000
    assert body["presets"][0]["words"] == "۲ میلیون تومان"
    assert body["return"]["key"] == "listing" and body["return"]["url"] == "/express/partner/lands/123"
    assert body["min_amount"] == 1000 and body["gateway"]["label"] == "زرین‌پال"
    assert body["texts"]["amount_question"] == "چقدر می‌خواهید کیف پولتان را شارژ کنید؟"
    assert set(body["wallet"]) >= {"available", "blocked", "total", "lines"}


@pytest.mark.parametrize("reason,line", [
    ("restore", "برای برگرداندن این آگهی به فهرست فعال ۵۰۰٬۰۰۰ تومان کم دارید."),
    ("sold", "برای ثبت فروش این آگهی ۵۰۰٬۰۰۰ تومان کم دارید."),
    ("deal", "برای تأیید نهایی این معامله ۵۰۰٬۰۰۰ تومان کم دارید."),
])
def test_reason_lines(client, app, reason, line):
    _partners()
    _login(client, OWNER)
    assert _api(client, ctx=_ctx(app, shortfall=500_000, reason=reason))["reason_line"] == line


def test_tampered_or_foreign_context_is_ignored(client, app):
    _partners()
    _login(client, OWNER)
    good = _ctx(app)
    for bad in (good[:-2] + "xx", _ctx(app, phone=OTHER), "not-a-token"):
        body = _api(client, ctx=bad)
        assert body["prefill"] == 0 and body["reason_line"] == "" and body["return"]["key"] == "wallet"


def test_small_shortfall_prefills_minimum(client, app):
    _partners()
    _login(client, OWNER)
    body = _api(client, ctx=_ctx(app, shortfall=300))
    assert body["prefill"] == 1000 and "۳۰۰ تومان" in body["reason_line"]


def test_legacy_shortfall_param_still_prefills_generic(client, app):
    _partners()
    _login(client, OWNER)
    body = _api(client, shortfall="750000")
    assert body["prefill"] == 750_000 and body["reason_line"] == "برای ادامه ۷۵۰٬۰۰۰ تومان کم دارید."
    assert _api(client, shortfall="-5")["prefill"] == 0
    assert _api(client, shortfall="abc")["prefill"] == 0
    assert _api(client, shortfall=str(10 ** 13))["prefill"] == 0


def test_publish_shortfall_response_carries_signed_context(client, app):
    from app.listings.service import create_listing

    _partners()
    with app.app_context():
        code = str(create_listing({"title": "ملک", "city": "کرج", "price_total": 1_000_000_000}, owner=OWNER)["code"])
    _login(client, OWNER)
    resp = client.post("/express/partner/api/my-property/publish",
                       json={"code": code, "payment_method": "نقدی", "commission_pct": 2})
    body = resp.get_json()
    assert resp.status_code == 400 and body["error_code"] == "wallet_insufficient"
    assert body["charge_path"] == "/express/partner/wallet/charge"  # old APKs
    assert body["charge_reason"] == "publish" and body["charge_context"]
    opts = _api(client, ctx=body["charge_context"])
    assert opts["prefill"] == body["shortfall"] == 20_000_000
    assert opts["reason_line"] == "برای انتشار این آگهی ۲۰٬۰۰۰٬۰۰۰ تومان کم دارید."
    assert opts["return"] == {"key": "listing", "code": code, "label": "بازگشت به آگهی",
                              "url": f"/express/partner/lands/{code}"}
    # وب: انتشار با کمبود مستقیم به صفحهٔ شارژ با همان زمینه می‌رود.
    page = client.post("/express/partner/my-property/publish",
                       data={"code": code, "payment_method": "نقدی", "commission_pct": "2"})
    assert page.status_code == 302 and page.headers["Location"].startswith(CHARGE + "?ctx=")
    html = client.get(page.headers["Location"]).get_data(as_text=True)
    assert "برای انتشار این آگهی ۲۰٬۰۰۰٬۰۰۰ تومان کم دارید." in html
    assert "data-wallet-charge" in html and 'name="ctx"' in html


# ------------------------------------------------------------- start: amount + allowlist

def test_amount_is_validated_server_side(client, app, gateway):
    _partners()
    _login(client, OWNER)
    for bad in (0, 999, "abc", 10 ** 12):
        resp = client.post(CHARGE, json={"amount": bad})
        assert resp.status_code == 400
    assert _rows() == [] and gateway["requests"] == []
    body = _start(client, amount="۱٬۲۰۰٬۰۰۰")
    assert _rows()[0]["commission_amount"] == 1_200_000
    assert gateway["requests"][0]["amount_toman"] == 1_200_000
    assert body["pay_url"].startswith("https://sandbox.zarinpal.com/") and body["txn_id"] == _rows()[0]["id"]
    assert body["status_path"] == f"/express/partner/api/wallet/topup/{body['txn_id']}"


def test_old_apk_body_still_works(client, gateway):
    _partners()
    _login(client, OWNER)
    resp = client.post(CHARGE, json={"amount": 100000})
    body = resp.get_json()
    assert resp.status_code == 200 and body["ok"] and body["pay_url"]
    row = _rows()[0]
    assert row["status"] == "pending" and row["return_target"] == "wallet"
    # callback still lands on Zarinpal's whitelisted route
    assert gateway["requests"][0]["callback_url"].endswith(CALLBACK)


def test_return_target_comes_only_from_allowlist(client, app, gateway):
    _partners()
    _login(client, OWNER)
    for evil in ("https://evil.example/", "//evil.example", "listing", "deal", "javascript:alert(1)"):
        _start(client, amount=100_000, **{"return": evil})
    keys = {r["return_target"] for r in _rows()}
    assert keys == {"wallet"}
    _start(client, amount=100_000, **{"return": "commissions"})
    assert _rows()[-1]["return_target"] == "commissions"
    # آگهی فقط از زمینهٔ امضاشده
    _start(client, amount=100_000, ctx=_ctx(app, code="77"))
    last = _rows()[-1]
    assert last["return_target"] == "listing" and last["return_code"] == "77" and last["charge_reason"] == "publish"
    # کد بد در زمینه هم به آدرس دلخواه تبدیل نمی‌شود
    _start(client, amount=100_000, ctx=_ctx(app, code="../../evil"))
    assert _rows()[-1]["return_target"] == "wallet"


def test_return_target_helper_never_builds_foreign_urls(app):
    from app.express_partner.wallet_charge_flow import return_target

    with app.test_request_context():
        assert return_target("listing", "12")["url"] == "/express/partner/lands/12"
        assert return_target("listing", "")["key"] == "wallet"
        assert return_target("https://evil.example")["url"] == "/express/partner/wallet"
        assert return_target("deal")["url"] == "/express/partner/inbox-visits"
        for key in ("commissions", "wallet", "listing", "deal"):
            assert return_target(key, "5")["url"].startswith("/express/partner/")


# ------------------------------------------------------------- callback → result states

def _callback(client, authority, status="OK"):
    return client.get(CALLBACK, query_string={"Authority": authority, "Status": status})


def test_success_result_shows_amount_balance_ref_and_return(client, app, gateway):
    _partners()
    _login(client, OWNER)
    body = _start(client, amount=2_000_000, ctx=_ctx(app, code="55"))
    auth = _rows()[0]["authority"]
    loc = _result_url(_callback(client, auth))
    assert loc.startswith("/express/partner/wallet/charge/result?t=")
    html = client.get(loc).get_data(as_text=True)
    assert 'data-wallet-result="success"' in html
    assert "کیف پولتان شارژ شد" in html and "۲٬۰۰۰٬۰۰۰ تومان" in html
    assert "REF-1" not in html and "data-wallet-result-ref" in html  # Persian digits only
    assert 'data-wallet-return="listing"' in html and 'href="/express/partner/lands/55"' in html
    assert "data-wallet-result-balance" in html
    status = client.get(body["status_path"]).get_json()
    assert status["state"] == "success" and status["ref_id"] == "REF-1" and status["balance"] >= 2_000_000
    assert status["return"]["key"] == "listing"
    # amount verified is the server record, not anything from the client
    assert gateway["verify_calls"][0]["amount_toman"] == 2_000_000


def test_cancel_result_reassures_and_offers_retry(client, app, gateway):
    _partners()
    _login(client, OWNER)
    _start(client, amount=300_000, ctx=_ctx(app, shortfall=300_000, reason="deal", code=""))
    row = _rows()[0]
    loc = _result_url(_callback(client, row["authority"], "NOK"))
    html = client.get(loc).get_data(as_text=True)
    assert 'data-wallet-result="cancelled"' in html
    assert "پرداخت لغو شد" in html and "پولی از حسابتان کم نشد" in html
    assert gateway["verify_calls"] == []
    assert _rows()[0]["status"] == "rejected"
    retry = re.search(r'href="([^"]+)" data-wallet-retry', html).group(1).replace("&amp;", "&")
    assert retry.startswith(CHARGE + "?from=")
    opts = _api(client, **{"from": parse_qs(urlparse(retry).query)["from"][0]})
    assert opts["prefill"] == 300_000 and opts["return"]["key"] == "deal"
    assert opts["reason_line"] == "برای تأیید نهایی این معامله ۳۰۰٬۰۰۰ تومان کم دارید."


def test_failed_result_mentions_72h_refund(client, gateway):
    _partners()
    _login(client, OWNER)
    _start(client, amount=300_000)
    gateway["verify"] = {"ok": False, "code": -51}
    html = client.get(_result_url(_callback(client, _rows()[0]["authority"]))).get_data(as_text=True)
    assert 'data-wallet-result="failed"' in html
    assert "پرداخت انجام نشد" in html and "۷۲ ساعت" in html


def test_pending_is_honest_and_recheck_verifies_with_gateway(client, gateway):
    _partners()
    _login(client, OWNER)
    body = _start(client, amount=400_000)
    gateway["verify"] = {"ok": False, "error": "timeout"}  # dropped response, retryable
    loc = _result_url(_callback(client, _rows()[0]["authority"]))
    html = client.get(loc).get_data(as_text=True)
    assert 'data-wallet-result="pending"' in html and "هنوز مشخص نیست" in html
    assert "data-wallet-recheck" in html
    assert _rows()[0]["status"] == "pending"
    status = client.get(body["status_path"]).get_json()
    assert status["state"] == "pending" and status["can_recheck"] is True and "balance" not in status
    gateway["verify"] = {"ok": True, "ref_id": "REF-9"}
    after = client.post(body["status_path"] + "/recheck").get_json()
    assert after["state"] == "success" and after["ref_id"] == "REF-9"
    # web recheck after success is a no-op
    t = parse_qs(urlparse(loc).query)["t"][0]
    calls = len(gateway["verify_calls"])
    client.post("/express/partner/wallet/charge/result/recheck", data={"t": t})
    assert len(gateway["verify_calls"]) == calls


def test_unknown_or_missing_token_shows_not_found(client):
    _partners()
    _login(client, OWNER)
    for url in ("/express/partner/wallet/charge/result", "/express/partner/wallet/charge/result?t=junk"):
        html = client.get(url).get_data(as_text=True)
        assert 'data-wallet-result="not_found"' in html and "این پرداخت پیدا نشد" in html
    loc = _result_url(_callback(client, "NOPE"))
    assert loc == "/express/partner/wallet/charge/result"


def test_result_without_session_hides_balance_and_return(app, gateway):
    """APK پرداخت را در مرورگر بیرونی باز می‌کند؛ آنجا نشست نیست."""
    _partners()
    owner = app.test_client()
    _login(owner, OWNER)
    _start(owner, amount=500_000, ctx=_ctx(app, code="9"))
    browser = app.test_client()
    loc = _result_url(_callback(browser, _rows()[0]["authority"]))
    html = browser.get(loc).get_data(as_text=True)
    assert 'data-wallet-result="success"' in html
    assert "data-wallet-result-balance" not in html and "data-wallet-return" not in html
    assert "data-wallet-back-app" in html and "/express/partner/commissions?topup=" in html


def test_other_user_cannot_read_or_recheck_topup(client, gateway):
    _partners()
    _login(client, OWNER)
    body = _start(client, amount=500_000)
    _login(client, OTHER)
    assert client.get(body["status_path"]).status_code == 404
    assert client.post(body["status_path"] + "/recheck").status_code == 404
    assert gateway["verify_calls"] == []


# ------------------------------------------------------------- idempotency / security

def test_callback_replay_credits_once(client, gateway):
    from app.express_partner.wallet_charge_flow import topup_state

    _partners()
    _login(client, OWNER)
    _start(client, amount=1_000_000)
    auth = _rows()[0]["authority"]
    before = client.get("/express/partner/api/wallet").get_json()["wallet"]["available"]
    for _ in range(3):
        _callback(client, auth)
    rows = _rows()
    assert len(rows) == 1 and topup_state(rows[0]) == "success"
    assert len(gateway["verify_calls"]) == 1
    after = client.get("/express/partner/api/wallet").get_json()["wallet"]["available"]
    assert after - before == 1_000_000
    # NOK replay after success does not undo it
    _callback(client, auth, "NOK")
    assert _rows()[0]["status"] == "approved"


def test_unverified_topup_is_never_credited(client, gateway):
    _partners()
    _login(client, OWNER)
    _start(client, amount=1_000_000)
    gateway["verify"] = {"ok": False, "error": "amount_mismatch"}
    _callback(client, _rows()[0]["authority"])
    assert client.get("/express/partner/api/wallet").get_json()["wallet"]["available"] == 0
    assert _rows()[0]["status"] == "rejected"


def test_web_form_requires_csrf(app, gateway):
    _partners()
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    _login(c, OWNER)
    resp = c.post(CHARGE, data={"amount": "100000"})
    assert "zarinpal" not in (resp.headers.get("Location") or "")
    assert _rows() == [] and gateway["requests"] == []
    html = c.get(CHARGE).get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    ok = c.post(CHARGE, data={"amount": "۱۰۰٬۰۰۰", "csrf_token": token})
    assert ok.status_code == 302 and ok.headers["Location"].startswith("https://sandbox.zarinpal.com/")
    assert _rows()[0]["commission_amount"] == 100_000


# ------------------------------------------------------------- pages and feed

def test_wallet_page_header_and_grouped_feed(client, gateway):
    from app.utils.storage import load_express_commissions, save_express_commissions

    _partners()
    _fund(OWNER, 5_000_000)
    rows = list(load_express_commissions() or [])
    rows.append({"id": 90, "commission_type": "escrow_hold", "partner_phone": OWNER, "land_code": "44",
                 "commission_amount": 1_500_000, "status": "held", "source": "sale_publish_escrow",
                 "created_at": "2026-11-10T08:00:00Z"})
    rows.append({"id": 91, "commission_type": "escrow_hold", "partner_phone": OWNER, "land_code": "45",
                 "commission_amount": 700_000, "status": "released", "source": "sale_publish_escrow",
                 "created_at": "2026-11-09T08:00:00Z"})
    save_express_commissions(rows)
    _login(client, OWNER)
    _start(client, amount=250_000)
    _callback(client, _rows()[0]["authority"], "NOK")
    html = client.get("/express/partner/wallet").get_data(as_text=True)
    assert "موجودی قابل استفاده" in html and "بلوکه برای پورسانت" in html and "کل موجودی" in html
    assert "۳٬۵۰۰٬۰۰۰ تومان" in html  # 5M − 1.5M held
    assert "افزایش اعتبار" in html
    for kind in ("hold", "release", "topup"):
        assert f'data-wallet-txn="{kind}"' in html
    assert "لغو شد" in html
    groups = client.get("/express/partner/api/wallet").get_json()["groups"]
    kinds = {it["kind"]: it for g in groups for it in g["entries"]}
    assert kinds["hold"]["sign"] == "-" and kinds["hold"]["chip"]["label"] == "بلوکه"
    assert kinds["release"]["chip"]["label"] == "آزاد شد"
    assert kinds["topup"]["chip"] == {"label": "لغو شد", "tone": "red"} and kinds["topup"]["tone"] == "muted"
    labels = [g["label"] for g in groups]
    assert len(labels) == len(set(labels))


def test_charge_page_renders_steps(client, app):
    _partners()
    _login(client, OWNER)
    html = client.get(CHARGE + "?return=commissions").get_data(as_text=True)
    assert 'data-wc-step="amount"' in html and 'data-wc-step="summary"' in html
    assert "چقدر می‌خواهید کیف پولتان را شارژ کنید؟" in html
    assert "کمترین مبلغ شارژ ۱٬۰۰۰ تومان است." in html
    assert "مبلغ فقط بعد از تأیید پرداخت از طرف بانک به کیف پولتان اضافه می‌شود." in html
    assert 'data-href="/express/partner/commissions"' in html and ">پرداخت<" in html


def test_amount_words():
    from app.express_partner.wallet_charge_flow import amount_words

    assert amount_words(2_500_000) == "۲ میلیون و ۵۰۰ هزار تومان"
    assert amount_words(1_500) == "۱ هزار و ۵۰۰ تومان"
    assert amount_words(1_000_000_000) == "۱ میلیارد تومان"
    assert amount_words(0) == ""
