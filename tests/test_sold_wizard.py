# -*- coding: utf-8 -*-
"""پرسش‌نامهٔ مرحله‌ای «فروخته شد» (سبک دیوار): فیلدهای تازه، اعتبارسنجی، سازگاری با کلاینت قدیمی،
خروج «هنوز قطعی نشده» بدون تغییر، نمایش در ادمین و صفحهٔ موفقیت. منطق بلوکه دست نخورده است."""
from __future__ import annotations

import re

import pytest

from test_owner_sold_hardening import (  # noqa: F401  (fixtures)
    MARKETER,
    OTHER,
    OWNER,
    _hold,
    _login,
    _publish,
    _visit,
    app,
    client,
)

SOLD = "/express/partner/api/my-property/sold"
OPTIONS = "/express/partner/api/my-property/sold-options?code={}"


@pytest.fixture
def audits(monkeypatch):
    calls = []
    import app.listings.owner_sold as mod

    real = mod._audit

    def spy(action, **kw):
        calls.append((action, kw))
        return real(action, **kw)

    monkeypatch.setattr(mod, "_audit", spy)
    return calls


def _land(code):
    from app.listings.service import get_listing

    return get_listing(code)


def test_options_are_backward_compatible_and_carry_wizard_copy(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    opts = client.get(OPTIONS.format(code)).get_json()
    # old keys untouched (APK 3b25b0a / 16d4e07 read these)
    for key in ("ok", "code", "sold", "can_mark_sold", "visits", "review_required_if_outside",
                "outside_confirm_message", "outside_label", "question", "held_amount"):
        assert key in opts
    assert opts["wizard_version"] == 1
    assert opts["texts"]["channel_question"] == "ملک‌تان از چه راهی فروخته شد؟"
    assert [c["value"] for c in opts["channels"]] == ["vinor", "outside", "not_final"]
    vinor = opts["channels"][0]
    assert vinor["enabled"] is False and "بازدید" in vinor["hint"]
    assert [s["value"] for s in opts["sources"]] == ["agency", "acquaintance", "other_platform", "other"]
    assert [s["label"] for s in opts["sources"]] == ["مشاور املاک", "آشنا و همسایه", "سایت یا اپ دیگر", "سایر"]
    assert "برمی‌گردد" in opts["outside_summary"] and "تومان" in opts["outside_summary"]
    assert opts["rating_labels"]["5"] == "عالی"


def test_visit_rows_have_name_date_status_and_summary(client, app):
    with app.app_context():
        code = _publish()
        _visit(code, "done_pending")
    _login(client, OWNER)
    opts = client.get(OPTIONS.format(code)).get_json()
    assert opts["channels"][0]["enabled"] is True
    v = opts["visits"][0]
    assert v["partner_name"] == "بازاریاب" and v["visit_date_label"]
    assert v["status_label"] == "منتظر تأیید انجام بازدید"
    assert "بلوکه" in v["summary"] and "بازاریاب" in v["summary"]
    assert "بررسی" in opts["outside_summary"]


def test_outside_with_answers_is_stored_but_escrow_unchanged(client, app, audits):
    with app.app_context():
        code = _publish()
        held = int(_hold(code)["commission_amount"])
    _login(client, OWNER)
    resp = client.post(SOLD, json={"code": code, "channel": "outside", "sold_source": "agency",
                                   "final_price": "۲٬۵۰۰٬۰۰۰٬۰۰۰"})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["details"]["sold_source"] == "agency"
    assert body["details"]["final_price"] == 2_500_000_000
    assert body["success_title"] == "فروش ثبت شد"
    assert any("به کیف پول شما برگشت" in s for s in body["next_steps"])
    with app.app_context():
        extras = _land(code)["extras"]
        assert extras["sold_source"] == "agency" and extras["sold_final_price"] == 2_500_000_000
        assert extras["sold_wizard_version"] == 1
        hold = _hold(code)
        # same release as before PR: amount untouched, final price ignored
        assert hold["status"] == "released" and hold["release_reason"] == "owner_sold_outside"
        assert int(hold["commission_amount"]) == held
    action, kw = next(a for a in audits if a[0] == "owner_mark_sold")
    assert kw["payload"]["answers"] == {"sold_source": "agency", "final_price": 2_500_000_000}


def test_vinor_with_rating_pays_declared_commission_not_final_price(client, app, audits):
    with app.app_context():
        code = _publish()
        visit = _visit(code, "completed")
        from app.utils.storage import save_express_assignments
        save_express_assignments([{"land_code": code, "partner_phone": MARKETER, "status": "active"}])
        held = int(_hold(code)["commission_amount"])
    _login(client, OWNER)
    resp = client.post(SOLD, json={"code": code, "channel": "vinor", "visit_id": visit["id"],
                                   "final_price": 9_000_000_000, "marketer_rating": 5,
                                   "comment": "  خیلی پیگیر بود  "})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["details"]["marketer_rating"] == 5
    assert any("بازاریاب" in s for s in body["next_steps"])
    with app.app_context():
        from app.utils.storage import load_express_commissions

        extras = _land(code)["extras"]
        assert extras["sold_marketer_rating"] == 5 and extras["sold_marketer_comment"] == "خیلی پیگیر بود"
        assert extras["sold_final_price"] == 9_000_000_000
        deals = [r for r in load_express_commissions() if r.get("commission_type") == "deal"]
        assert len(deals) == 1 and int(deals[0]["commission_amount"]) == held
        assert _hold(code)["status"] == "settled"
    _a, kw = next(a for a in audits if a[0] == "owner_mark_sold")
    assert kw["payload"]["answers"]["marketer_rating"] == 5


@pytest.mark.parametrize("channel,extra,code_", [
    ("outside", {"sold_source": "divar"}, "invalid_sold_source"),
    ("outside", {"final_price": "12abc"}, "invalid_final_price"),
    ("outside", {"final_price": 0}, "invalid_final_price"),
    ("outside", {"final_price": "-5"}, "invalid_final_price"),
    ("outside", {"final_price": 10 ** 14}, "invalid_final_price"),
    ("outside", {"final_price": 12.5}, "invalid_final_price"),
    ("outside", {"marketer_rating": 4}, "rating_vinor_only"),
    ("outside", {"comment": "سلام"}, "rating_vinor_only"),
    ("vinor", {"marketer_rating": 6}, "invalid_rating"),
    ("vinor", {"marketer_rating": "x"}, "invalid_rating"),
    ("vinor", {"marketer_rating": True}, "invalid_rating"),
    ("vinor", {"marketer_rating": 3, "comment": "ا" * 301}, "comment_too_long"),
    ("vinor", {"sold_source": "agency"}, "source_outside_only"),
])
def test_invalid_answers_are_rejected_before_any_change(client, app, channel, extra, code_):
    with app.app_context():
        code = _publish()
        visit = _visit(code, "completed")
    _login(client, OWNER)
    payload = {"code": code, "channel": channel, **extra}
    if channel == "vinor":
        payload["visit_id"] = visit["id"]
    resp = client.post(SOLD, json=payload)
    body = resp.get_json()
    assert resp.status_code == 400 and body["error_code"] == code_, body
    assert body["error"] and any(ord(ch) > 127 for ch in body["error"])
    with app.app_context():
        from app.utils.storage import load_express_commissions, load_express_visit_requests

        assert _land(code).get("express_status") != "sold"
        hold = _hold(code)
        assert hold["status"] == "held" and not hold.get("review_required")
        assert not [r for r in load_express_commissions() if r.get("commission_type") == "deal"]
        row = next(r for r in load_express_visit_requests() if r.get("id") == visit["id"])
        assert not row.get("deal_decision")


def test_old_client_without_answers_still_works(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    resp = client.post(SOLD, json={"code": code, "channel": "outside"})
    assert resp.status_code == 200 and resp.get_json()["sold"] is True
    with app.app_context():
        extras = _land(code)["extras"]
        assert "sold_source" not in extras and "sold_final_price" not in extras
        assert extras["sold_wizard_version"] == 0
        assert _hold(code)["status"] == "released"


def test_empty_optional_answers_are_ignored(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    resp = client.post(SOLD, json={"code": code, "channel": "outside", "sold_source": "",
                                   "final_price": "", "marketer_rating": "", "comment": ""})
    assert resp.status_code == 200, resp.get_json()
    with app.app_context():
        assert "sold_final_price" not in _land(code)["extras"]


def test_not_final_is_a_noop(client, app, audits):
    with app.app_context():
        code = _publish()
        _visit(code, "completed")
        before = dict(_land(code))
        hold_before = dict(_hold(code))
    _login(client, OWNER)
    resp = client.post(SOLD, json={"code": code, "channel": "not_final", "final_price": "abc"})
    body = resp.get_json()
    assert resp.status_code == 200 and body["noop"] is True and body["sold"] is False
    assert "تغییری ثبت نشد" in body["message"]
    with app.app_context():
        assert _land(code) == before
        assert _hold(code) == hold_before
    assert audits == []
    # form post (web) goes back to my-property
    page = client.get(f"/express/partner/my-property/{code}/sold").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    resp = client.post(SOLD, data={"code": code, "channel": "not_final", "csrf_token": token})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/express/partner/my-property")
    # ownership still enforced
    _login(client, OTHER)
    resp = client.post(SOLD, json={"code": code, "channel": "not_final"})
    assert resp.status_code == 403


def test_repeat_does_not_overwrite_answers(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    assert client.post(SOLD, json={"code": code, "channel": "outside", "sold_source": "agency"}).status_code == 200
    again = client.post(SOLD, json={"code": code, "channel": "outside", "sold_source": "other"})
    assert again.status_code == 200 and again.get_json()["already"] is True
    with app.app_context():
        assert _land(code)["extras"]["sold_source"] == "agency"


def test_review_case_shows_answers_on_admin_page(client, app):
    with app.app_context():
        code = _publish()
        _visit(code, "completed")
    _login(client, OWNER)
    resp = client.post(SOLD, json={"code": code, "channel": "outside", "sold_source": "acquaintance",
                                   "final_price": 1_800_000_000})
    body = resp.get_json()
    assert body["review_required"] is True and body["hold_released"] is False
    assert any("بررسی" in s for s in body["next_steps"])
    with app.app_context():
        hold = _hold(code)
        assert hold["status"] == "held" and hold["review_required"] is True
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    html = client.get("/admin/express/commissions/escrow-review").get_data(as_text=True)
    assert f'data-sold-answers="{code}"' in html and "آشنا و همسایه" in html
    assert f'data-owner-sale="{code}"' in html


def test_admin_lists_vinor_rating_and_comment(client, app):
    with app.app_context():
        code = _publish()
        visit = _visit(code, "completed")
        from app.utils.storage import save_express_assignments
        save_express_assignments([{"land_code": code, "partner_phone": MARKETER, "status": "active"}])
    _login(client, OWNER)
    assert client.post(SOLD, json={"code": code, "channel": "vinor", "visit_id": visit["id"],
                                   "marketer_rating": "۴", "comment": "خوب"}).status_code == 200
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    html = client.get("/admin/express/commissions/escrow-review").get_data(as_text=True)
    row = html.split(f'data-owner-sale="{code}"', 1)[1].split("</tr>", 1)[0]
    assert "★★★★" in row and "(4/5)" in row and "خوب" in row and "بازدید وینور" in row


def test_web_wizard_steps_and_success_screen(client, app):
    with app.app_context():
        code = _publish()
        _visit(code, "done_pending")
    _login(client, OWNER)
    html = client.get(f"/express/partner/my-property/{code}/sold").get_data(as_text=True)
    for step in ("channel", "visit", "source", "price", "rating", "summary"):
        assert f'data-sw-step="{step}"' in html
    for text in ("ملک‌تان از چه راهی فروخته شد؟", "کدام بازدید به فروش رسید؟", "از چه طریقی فروختید؟",
                 "قیمت نهایی فروش چقدر بود؟", "از بازاریاب راضی بودید؟", "ثبت فروش",
                 "هنوز قطعی نشده / منصرف شدم", "منتظر تأیید انجام بازدید"):
        assert text in html
    assert "data-sw-progress" in html and "data-sw-back" in html
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    resp = client.post(SOLD, data={"code": code, "channel": "outside", "sold_source": "other_platform",
                                   "final_price": "2,100,000,000", "csrf_token": token})
    assert resp.status_code == 302 and resp.headers["Location"].endswith(f"/my-property/{code}/sold/done")
    done = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "فروش ثبت شد" in done and "fa-check" in done and "سایت یا اپ دیگر" in done
    from app.express_partner.deal_wallet import toman_fa
    assert toman_fa(2_100_000_000) in done
    assert "بررسی" in done  # done_pending visit → review copy
    _login(client, OTHER)
    assert client.get(f"/express/partner/my-property/{code}/sold/done").status_code == 403


def test_bad_form_answers_flash_and_return_to_wizard(client, app):
    with app.app_context():
        code = _publish()
    _login(client, OWNER)
    html = client.get(f"/express/partner/my-property/{code}/sold").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    resp = client.post(SOLD, data={"code": code, "channel": "outside", "final_price": "abc", "csrf_token": token})
    assert resp.status_code == 302 and resp.headers["Location"].endswith(f"/my-property/{code}/sold")
    with app.app_context():
        assert _land(code).get("express_status") != "sold"
