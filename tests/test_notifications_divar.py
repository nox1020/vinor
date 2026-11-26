# -*- coding: utf-8 -*-
"""صفحهٔ «اعلان‌ها» به سبک دیوار (وب) — هم‌تراز با NotificationFeed.kt / NotificationsFragment اپ."""
from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

from app.express_partner import notifications_feed as F

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "app/express_partner/templates/express_partner/notifications.html"

# 2026-11-26 12:00 Tehran = 08:30 UTC
NOW = 1795681800  # 2026-11-26 08:30 UTC = 12:00 Tehran


def test_kind_classification():
    assert F.kind_of({"type": "visit"}) == "visit"
    assert F.kind_of({"type": "info", "source": "visit_inbox"}) == "visit"
    assert F.kind_of({"action_url": "/express/partner/requests?tab=visits"}) == "visit"
    assert F.kind_of({"title": "واریز پورسانت"}) == "wallet"
    assert F.kind_of({"action_url": "/express/partner/commissions"}) == "wallet"
    assert F.kind_of({"title": "فایل جدید اکسپرس", "type": "info"}) == "listing"
    assert F.kind_of({"ad_id": "1290"}) == "listing"
    assert F.kind_of({"type": "sales_coach", "title": "نکتهٔ امروز"}) == "general"
    assert F.kind_of({}) == "general"


def test_safe_link_only_internal():
    assert F.safe_link("/express/partner/requests?tab=visits") == "/express/partner/requests?tab=visits"
    assert F.safe_link("https://vinor.ir/express/partner/wallet") == "/express/partner/wallet"
    assert F.safe_link("https://www.vinor.ir/ai") == "/ai"
    assert F.safe_link("//evil.example/x") is None
    assert F.safe_link("https://evil.example/x") is None
    assert F.safe_link("javascript:alert(1)") is None
    assert F.safe_link(None) is None and F.safe_link("  ") is None


def test_epoch_and_buckets_and_short_time():
    assert F.epoch_of(NOW) == NOW
    assert F.epoch_of(NOW * 1000) == NOW
    assert F.epoch_of("2026-11-26T08:30:00Z") == NOW
    assert F.epoch_of("") is None and F.epoch_of("nope") is None
    assert F.short_time(NOW - 20, NOW) == "همین حالا"
    assert F.short_time(NOW + 300, NOW) == "همین حالا"  # clock skew
    assert F.short_time(NOW - 9 * 60, NOW) == "۹ دقیقه پیش"
    assert F.short_time(NOW - 3 * 3600, NOW) == "۳ ساعت پیش"
    assert F.day_bucket(NOW - 3 * 3600, NOW) == "today"
    # 12:00 Tehran → 13h ago is yesterday 23:00 Tehran
    assert F.day_bucket(NOW - 13 * 3600, NOW) == "yesterday"
    assert F.short_time(NOW - 13 * 3600, NOW) == "دیروز"
    assert F.short_time(NOW - 3 * 86400, NOW) == "۳ روز پیش"
    assert F.day_bucket(NOW - 3 * 86400, NOW) == "older"
    assert F.short_time(NOW - 20 * 86400, NOW) == "۱۵ آبان"   # 2026-11-06 = 15 Aban 1405
    assert F.short_time(NOW - 400 * 86400, NOW).endswith("۱۴۰۴")
    assert F.day_bucket(None, NOW) == "older" and F.short_time(None, NOW) == ""


def _items():
    return [
        {"id": "a", "title": "درخواست بازدید", "body": "x", "type": "visit", "created_at": NOW - 600, "is_read": False,
         "action_url": "/express/partner/requests?tab=visits"},
        {"id": "b", "title": "واریز پورسانت", "body": "y", "type": "info", "created_at": NOW - 13 * 3600, "is_read": True},
        {"id": "c", "title": "فایل جدید", "body": "  z \n w ", "type": "info", "created_at": NOW - 9 * 86400, "is_read": False,
         "action_url": "https://evil.example"},
        {"id": "d", "title": "plus", "body": "", "type": "visit", "created_at": NOW, "is_read": False, "source": "visit_plus_user"},
    ]


def test_build_feed_groups_and_counts():
    feed = F.build_feed(_items(), now=NOW)
    assert [s["key"] for s in feed["sections"]] == ["today", "yesterday", "older"]
    assert [s["label"] for s in feed["sections"]] == ["امروز", "دیروز", "قدیمی‌تر"]
    assert feed["total"] == 3 and feed["unread"] == 2 and feed["unread_fa"] == "۲"  # plus-visit hidden like the app
    older = feed["sections"][2]["rows"][0]
    assert older["kind"] == "listing" and older["link"] is None and older["body"] == "z w"
    today = feed["sections"][0]["rows"][0]
    assert today["unread"] and today["link"] == "/express/partner/requests?tab=visits" and today["kind_label"] == "بازدید"


def test_template_structure_and_style():
    src = TPL.read_text(encoding="utf-8")
    # header = Customers / Tracking / Vinor-man
    assert "{{ ep_header_start(id='partnerNotificationsHeader') }}" in src
    assert "{% call ep_header_row('اعلان‌ها', url_for('express_partner.home'), inner_class='max-w-lg mx-auto w-full') %}" in src
    # tinted-outline active pill (Home filter language)
    active = re.search(r"#vinorNotifyPage \.vn-n-tab\.is-active \{(.*?)\}", src, re.S).group(1)
    assert "var(--vn-chip-on-bg)" in active and "var(--vn-chip-on-line)" in active
    assert "--vn-chip-on-bg: rgba(16,185,129,.14);" in src and "--vn-chip-line: rgba(255,255,255,.12);" in src
    tab = re.search(r"#vinorNotifyPage \.vn-n-tab \{(.*?)\}", src, re.S).group(1)
    assert "height: 32px;" in tab
    # hairlines, unread dot/tint, kind icons, 2-line body, hidden scrollbars
    assert "height: 1px; background: var(--vn-n-line);" in src and "--vn-n-line: rgba(255,255,255,.06);" in src
    assert ".vn-n-row.is-unread { background: rgba(16,185,129,.05); }" in src
    assert "-webkit-line-clamp: 2;" in src
    for k in ("visit", "wallet", "listing", "general"):
        assert f".vn-n-ico--{k}" in src
    assert "scrollbar-width: none;" in src and "*::-webkit-scrollbar { display: none;" in src
    for text in ("هیچ اعلانی نداری", "همه‌ی اعلان‌ها خوانده شدن", "خواندن همه", "خوانده‌نشده", "پستچی وینور"):
        assert text in src
    assert "بازنشر" not in src
    # pull-to-refresh: generic handler is not opted out on this page
    assert 'data-vinor-ptr="off"' not in src


def test_script_marks_read_navigates_and_filters():
    src = TPL.read_text(encoding="utf-8")
    assert "window.vinorCsrfFetchHeaders" in src
    assert "data-mark-one=\"{{ url_for('express_partner.mark_notification_read', notif_id='__ID__') }}\"" in src
    assert "data-mark-all=\"{{ url_for('express_partner.mark_all_notifications_read') }}\"" in src
    assert "window.vinorExpressNavigate(link, { forward: true })" in src
    assert "u.searchParams.set('tab', 'unread')" in src
    assert "Promise.race([req" in src


def _client(phone):
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_phone"] = phone
        sess["logged_in"] = True
        sess["VINOR_IS_EXPRESS_PARTNER"] = True
    return client


def _get(path, items):
    phone = "09121111111"
    with mock.patch("app.express_partner.partner_roles.partner_is_approved", return_value=True), \
         mock.patch("app.utils.storage.load_express_partners", return_value=[{"phone": phone, "status": "approved"}]), \
         mock.patch("app.services.notifications.get_user_notifications", return_value=items):
        return _client(phone).get(path)


def test_page_renders_feed_instead_of_redirect():
    resp = _get("/express/partner/notifications", _items())
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="partnerNotificationsHeader"' in html
    assert html.count("<li data-notify-item") == 3
    assert '<span class="vn-n-badge" data-notify-unread-badge>۲</span>' in html
    assert 'data-link="/express/partner/requests?tab=visits"' in html
    assert 'data-link="https://evil' not in html and html.count("data-link=") == 1
    assert 'class="vn-n-row is-unread"' in html
    assert 'data-notify-empty="all" hidden' in html
    assert 'href="/express/partner/home?ai=1&amp;thread=__postchi__"' in html


def test_unread_tab_and_empty_states():
    html = _get("/express/partner/notifications?tab=unread", _items()).get_data(as_text=True)
    assert 'data-tab="unread"' in html
    assert re.search(r'class="vn-n-tab is-active" data-notify-tab="unread"', html)
    read_only = [dict(n, is_read=True) for n in _items()]
    html = _get("/express/partner/notifications?tab=unread", read_only).get_data(as_text=True)
    assert 'data-notify-empty="unread">' in html  # visible
    assert "data-notify-read-all hidden" in html
    html = _get("/express/partner/notifications", []).get_data(as_text=True)
    assert 'data-notify-empty="all">' in html and 'data-notify-empty="unread" hidden' in html


def test_postchi_route_unchanged():
    with mock.patch("app.express_partner.partner_roles.partner_is_approved", return_value=True), \
         mock.patch("app.utils.storage.load_express_partners", return_value=[{"phone": "09121111111", "status": "approved"}]):
        resp = _client("09121111111").get("/express/partner/postchi")
    assert resp.status_code == 302 and "thread=__postchi__" in resp.headers["Location"]
