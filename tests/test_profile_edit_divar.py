# -*- coding: utf-8 -*-
"""صفحهٔ ویرایش پروفایل به سبک دیوار، هم‌تراز با پیگیری و مشتریان."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "app/express_partner/templates/express_partner"
PHONE = "09121234567"


def _src() -> str:
    return (TPL / "profile_edit.html").read_text(encoding="utf-8")


def test_header_matches_customers_and_requests():
    edit = _src()
    customers = (TPL / "customers.html").read_text(encoding="utf-8")
    requests = (TPL / "requests.html").read_text(encoding="utf-8")
    assert "{% from 'express_partner/partials/partner_header.html' import ep_header_start, ep_header_end, ep_header_row %}" in edit
    assert "{% call ep_header_row('ویرایش پروفایل', subpage_back_url(), inner_class='max-w-lg mx-auto w-full') %}{% endcall %}" in edit
    assert "id='profileEditHeader'" in edit or 'id="profileEditHeader"' in edit or "id='profileEditHeader'" in edit
    assert "inner_class='max-w-lg mx-auto w-full'" in customers
    assert "inner_class='max-w-lg mx-auto w-full'" in requests
    assert "subpage_back_url()" in customers and "subpage_back_url()" in requests
    # ذخیره از هدر به نوار پایین منتقل شده تا هدر مثل پیگیری/مشتریان فقط برگشت+عنوان باشد.
    header = edit[edit.index("ep_header_start"): edit.index("{{ ep_header_end() }}")]
    assert "profileEditSaveBtn" not in header


def test_sticky_save_and_divar_structure():
    src = _src()
    assert 'class="pe-savebar"' in src
    assert 'id="profileEditSaveBtn"' in src
    assert "ذخیره تغییرات" in src
    assert "scrollbar-width: none;" in src
    assert "*::-webkit-scrollbar" in src
    assert "--pe-card: #14181f;" in src or "--pe-card:#14181f;" in src.replace(" ", "")
    assert "--pe-muted: #8e8e93;" in src or "--rq-muted" in (TPL / "requests.html").read_text(encoding="utf-8")
    assert "border-bottom: 1px solid var(--pe-border);" in src
    assert 'id="profileName"' in src
    assert 'readonly' in src and "شماره موبایل قابل تغییر نیست" in src
    assert 'id="profileCityValue"' in src
    assert 'id="profileBirth"' in src
    assert 'id="bioInput"' in src
    assert 'id="deleteAccountOpen"' in src
    assert 'id="avatarEditForm"' in src
    assert "csrf_token" in src
    assert 'id="profileNameError"' in src
    assert "pe-input--error" in src
    assert "api_profile_update" in src


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-profile-edit-divar")
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
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with application.app_context():
        from app.utils import storage as S
        S.save_express_partners([
            {"phone": PHONE, "name": "مسعود حسینی", "status": "approved", "city": "تهران",
             "partner_tier": "special"},
        ])
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_edit_page_renders_divar_chrome(client):
    with client.session_transaction() as sess:
        sess["user_phone"] = PHONE
    html = client.get("/express/partner/profile/edit", follow_redirects=True).get_data(as_text=True)
    assert "ویرایش پروفایل" in html
    assert 'id="profileEditPage"' in html
    assert 'id="profileEditSaveBtn"' in html
    assert 'class="pe-savebar"' in html
    assert "ذخیره تغییرات" in html
    assert "شماره موبایل قابل تغییر نیست" in html
    assert PHONE in html or "0912" in html
    assert 'id="partnerProfileHeader"' not in html  # این صفحه هدر خودش را دارد


def test_back_from_profile_stays_on_vinor_man(client):
    with client.session_transaction() as sess:
        sess["user_phone"] = PHONE
    html = client.get("/express/partner/profile/edit?from=profile", follow_redirects=True).get_data(as_text=True)
    assert 'href="/express/partner/profile"' in html
    html_settings = client.get("/express/partner/profile/edit?from=settings", follow_redirects=True).get_data(as_text=True)
    assert 'href="/express/partner/settings"' in html_settings
