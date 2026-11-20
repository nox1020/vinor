# -*- coding: utf-8 -*-
"""کیف پول v2 در همهٔ ورودی‌های واقعی: /commissions (منو، خانه، پروفایل، کشو)، /wallet، کارت خانه و
پروفایل با «موجودی قابل استفاده»، و نبود کش کهنه (service worker / no-store)."""
from __future__ import annotations

import os
import re

import pytest

from test_owner_sold_hardening import (  # noqa: F401  (fixtures)
    OTHER,
    OWNER,
    _fund,
    _login,
    _partners,
    app,
    client,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD_MARKERS = ("commissionsRefreshMount", "data-withdraw-wizard", "vn-wallet-card", "commissions-financial.js",
               "کل موجودی", "کل درآمد", "پورسانت‌های قابل دریافت")


@pytest.fixture(autouse=True)
def _quiet_sms(monkeypatch):
    monkeypatch.setattr("app.express_partner.routes._send_withdrawal_admin_sms", lambda **_k: None)
    monkeypatch.setattr("app.express_partner.commission_sms.notify_partner_commission_txn", lambda **_k: None)


def _hold(phone, amount):
    from app.utils.storage import load_express_commissions, save_express_commissions

    rows = list(load_express_commissions() or [])
    rows.append({"id": 900 + len(rows), "commission_type": "escrow_hold", "partner_phone": phone,
                 "land_code": "77", "commission_amount": amount, "status": "held",
                 "source": "sale_publish_escrow", "created_at": "2026-11-10T08:00:00Z"})
    save_express_commissions(rows)


def _pending_withdrawal(phone, amount):
    from app.utils.storage import save_partner_withdrawals

    save_partner_withdrawals([{
        "id": "abcdef0123456789", "phone": phone, "amount": amount, "status": "pending",
        "bank_summary": "بانک ملت · IR82 •••• •••• 9002", "created_at": "2026-11-20T10:00:00Z",
    }])


@pytest.fixture
def funded(client):
    _partners()
    _fund(OWNER, 30_000_000)
    _hold(OWNER, 5_000_000)
    _pending_withdrawal(OWNER, 10_000_000)
    _login(client, OWNER)
    return client


@pytest.mark.parametrize("path", ["/express/partner/commissions", "/express/partner/wallet"])
def test_main_wallet_entry_points_render_v2(funded, path):
    resp = funded.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'data-wallet-style="v2"' in html and "wh-balance" in html
    for marker in OLD_MARKERS:
        assert marker not in html, marker
    # یک برچسب برای هر مفهوم: قابل استفاده = ۳۰ − ۵ بلوکه − ۱۰ در انتظار برداشت
    assert html.count("موجودی قابل استفاده") == 1
    assert re.search(r'data-wallet-available>\s*۱۵٬۰۰۰٬۰۰۰ تومان', html)
    assert html.count('data-wallet-line="blocked"') == 1 and "بلوکه برای پورسانت" in html
    assert html.count('data-wallet-line="pending_withdrawal"') == 1 and "در انتظار برداشت" in html
    # دکمه‌های چسبان و تایم‌لاین روزبه‌روز
    assert "data-wallet-topup" in html and 'href="/express/partner/wallet/withdraw"' in html
    assert 'class="wh-tl"' in html and "data-wallet-group" in html
    # ورودی اصلی است: نوار تب پایین هم هست
    assert 'id="bottomNavMenu"' in html
    assert "no-store" in resp.headers.get("Cache-Control", "")


def test_pending_partner_commissions_shows_guest_not_old_wallet(client):
    from app.utils.storage import save_express_partners

    save_express_partners([{"phone": OTHER, "name": "در انتظار", "status": "pending"}])
    _login(client, OTHER)
    html = client.get("/express/partner/commissions").get_data(as_text=True)
    assert 'id="commissionsRefreshMount"' not in html and "کل موجودی" not in html
    assert 'data-wallet-style="v2"' not in html


def test_home_data_exposes_available_balance_for_apk_cards(funded):
    data = funded.get("/express/partner/home/data").get_json()
    assert data["wallet_available"] == 15_000_000
    assert data["withdrawable_balance"] == 20_000_000  # سازگاری: کلید قدیمی دست‌نخورده


def test_profile_wallet_row_uses_available_balance(funded):
    html = funded.get("/express/partner/profile").get_data(as_text=True)
    m = re.search(r'>کیف پول</div>\s*<div[^>]*>([^<]+)<', html)
    digits = re.sub(r"[^۰-۹0-9]", "", m.group(1)) if m else ""
    assert digits in ("۱۵۰۰۰۰۰۰", "15000000"), m and m.group(1)


def test_service_worker_never_serves_stale_wallet():
    with open(os.path.join(ROOT, "app/static/express-partner-sw.js"), encoding="utf-8") as fh:
        sw = fh.read()
    assert "const VERSION = 'v1.0.69-offline-outbox'" not in sw  # نسخهٔ جدید = پاک‌شدن کش‌های قبلی
    assert "if (isWalletPath(url.pathname)) return;" in sw
    with open(os.path.join(ROOT, "app/static/express-partner/express-nav.js"), encoding="utf-8") as fh:
        assert "'/express/partner/wallet': { tab: 'profile'" in fh.read()


def test_legacy_wallet_json_endpoints_still_work(funded):
    assert funded.get("/express/partner/commissions/data").get_json()["wallet_available"] == 15_000_000
    assert funded.get("/express/partner/commissions/summary").status_code == 200
    body = funded.get("/express/partner/api/wallet").get_json()
    assert body["wallet"]["available"] == 15_000_000
