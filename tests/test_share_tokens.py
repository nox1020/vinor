# -*- coding: utf-8 -*-
"""Referral links are opaque. Older base64 phone links still resolve."""
from __future__ import annotations

import base64

import pytest

PHONE = "09124445566"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "unit-share-token-secret")


def test_new_token_hides_the_phone_and_round_trips():
    from app.utils.share_tokens import decode_partner_ref, encode_partner_ref

    token = encode_partner_ref(PHONE)
    assert token
    assert PHONE not in token
    padded = token + "=" * (-len(token) % 4)
    try:
        visible = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
    except Exception:
        visible = ""
    assert PHONE not in visible
    assert decode_partner_ref(token) == PHONE


def test_legacy_base64_link_still_resolves():
    from app.utils.share_tokens import decode_partner_ref

    legacy = base64.urlsafe_b64encode(PHONE.encode()).decode().rstrip("=")
    assert decode_partner_ref(legacy) == PHONE
    assert decode_partner_ref("not-a-token") == ""
    assert decode_partner_ref("") == ""


def test_plus98_encodes_to_the_canonical_mobile():
    from app.utils.share_tokens import decode_partner_ref, encode_partner_ref

    token = encode_partner_ref("+989124445566")
    assert decode_partner_ref(token) == PHONE


def test_short_referral_accepts_old_and_new_links(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-share-token-secret")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    from app import create_app
    from app.utils.share_tokens import encode_partner_ref

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    client = app.test_client()
    legacy = base64.urlsafe_b64encode(PHONE.encode()).decode().rstrip("=")
    fresh = encode_partner_ref(PHONE)
    for token in (legacy, fresh):
        resp = client.get(f"/r/{token}")
        assert resp.status_code in (301, 302, 303)
        assert "apply" in (resp.headers.get("Location") or "")
        with client.session_transaction() as sess:
            assert sess.get("referrer_phone") == PHONE
            sess.clear()
    junk = client.get("/r/not-a-real-token")
    assert junk.status_code in (301, 302, 303)
    with client.session_transaction() as sess:
        assert not sess.get("referrer_phone")
