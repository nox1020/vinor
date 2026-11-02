# -*- coding: utf-8 -*-
"""Wallet review items 2,3,4,7,9,10 (+1 in test_wallet_admin_status_lock)."""
from __future__ import annotations

import threading
import time

import pytest

PH = "09124000124"


@pytest.fixture
def app(tmp_path, monkeypatch):
    for k, v in {
        "INSTANCE_PATH": str(tmp_path), "SECRET_KEY": "unit-wallet", "SESSION_COOKIE_SECURE": "0",
        "VINOR_DISABLE_SMS_SCHEDULER": "1", "VINOR_DISABLE_REACH": "1", "VINOR_OPTIMIZATION_SCHEDULER": "0",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'v.db'}",
    }.items():
        monkeypatch.setenv(k, v)
    from app import create_app

    a = create_app()
    a.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return a


def _seed(app, comms, wds, banks=None):
    from app.utils import storage

    with app.app_context():
        storage.save_express_commissions(comms)
        storage.save_partner_withdrawals(wds)
        if banks is not None:
            storage.save_partner_bank_accounts(banks)


def test_amount_parser_rejects_bad_input_and_reads_persian_digits():
    from app.express_partner.partner_withdrawals import parse_amount_strict

    assert parse_amount_strict("۱۲،۰۰۰،۰۰۰") == 12_000_000
    assert parse_amount_strict("12,000,000") == 12_000_000
    for bad in ("-5", "1.5", "abc", "", None, True, -1, "9" * 16):
        assert parse_amount_strict(bad) is None, bad


def test_validate_new_request_reports_invalid_amount():
    from app.express_partner.partner_withdrawals import validate_new_request

    rec, err = validate_new_request("-20000000", "b1", PH, [{"id": "b1", "phone": PH}], [], [])
    assert rec is None and err == "invalid_amount"


def test_insufficient_message_no_longer_promises_a_topup():
    from app.express_partner.deal_wallet import wallet_insufficient_message

    msg = wallet_insufficient_message(5_000_000, 1_000_000)
    assert "پشتیبانی" in msg and "شارژ کنید" not in msg


def test_cancel_does_not_overwrite_a_fresh_commission(app, monkeypatch):
    """item 3: cancel used a stale cached commissions copy and saved it back."""
    from app.utils import storage

    monkeypatch.setattr("app.express_partner.commission_sms.notify_partner_commission_txn", lambda **k: None)
    _seed(app, [{"id": 1, "partner_phone": PH, "commission_amount": 30_000_000, "status": "approved"}],
          [{"id": "w1", "phone": PH, "amount": 10_000_000, "status": "pending"}])
    with app.app_context():
        storage.load_express_commissions_cached()  # warm the process cache
        comms = storage.load_express_commissions()
        comms.append({"id": 2, "partner_phone": PH, "commission_amount": 1, "status": "approved"})
        # write behind the cache's back (another worker) keeping same size/mtime is unrealistic; emulate
        # a stale cache by pinning it to the old list
        storage._COMMISSIONS_CACHE["data"] = [dict(comms[0])]
        path = storage.ensure_file('EXPRESS_COMMISSIONS_FILE', 'express_commissions.json', [], None)
        storage._save(path, comms)
        import os
        st = os.stat(path)
        storage._COMMISSIONS_CACHE.update({"path": path, "mtime": st.st_mtime_ns, "size": st.st_size})
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_phone"] = PH
    monkeypatch.setattr("app.express_partner.routes._is_partner_approved", lambda *a, **k: True, raising=False)
    from app.express_partner import routes
    with app.test_request_context():
        from flask import session
        session["user_phone"] = PH
        resp = routes._withdrawals_cancel_locked("w1")
        body = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        assert body["success"], body
    with app.app_context():
        assert 2 in [r["id"] for r in storage.load_express_commissions()]
        assert storage.load_partner_withdrawals()[0]["status"] == "cancelled"


def test_page_reconcile_uses_lock_and_keeps_concurrent_writes(app):
    """item 2: reconcile on page view mutated the shared cache and saved without the lock."""
    from app.express_partner import routes
    from app.express_partner.deal_wallet import commission_store_lock
    from app.utils import storage

    _seed(app, [{"id": 1, "partner_phone": PH, "commission_amount": 30_000_000, "status": "approved"}],
          [{"id": "w1", "phone": PH, "amount": 10_000_000, "status": "paid"}])
    done = threading.Event()

    def page_view():
        with app.test_request_context():
            routes._reconcile_partner_commissions(PH)
        done.set()

    with app.app_context():
        cached_before = storage.load_express_commissions_cached()
        with commission_store_lock():
            t = threading.Thread(target=page_view)
            t.start()
            assert not done.wait(0.5)
            comms = storage.load_express_commissions()
            comms.append({"id": 2, "partner_phone": PH, "commission_amount": 5, "status": "approved"})
            storage.save_express_commissions(comms)
        t.join(5)
        assert done.is_set()
        rows = storage.load_express_commissions()
        assert 2 in [r["id"] for r in rows]
        assert storage.load_partner_withdrawals()[0].get("commission_allocated_amount") == 10_000_000
        assert cached_before[0]["commission_amount"] == 30_000_000  # shared cache untouched


def test_withdrawal_sms_runs_after_the_lock_is_released(app, monkeypatch):
    """item 7."""
    from app.express_partner import deal_wallet, routes

    seen = []

    def fake_sms(**kw):
        seen.append(deal_wallet._LOCK_DEPTH)

    monkeypatch.setattr(routes, "_send_withdrawal_admin_sms", fake_sms)
    monkeypatch.setattr("app.express_partner.commission_sms.notify_partner_commission_txn", fake_sms)
    _seed(app, [{"id": 1, "partner_phone": PH, "commission_amount": 30_000_000, "status": "approved"}], [],
          banks=[{"id": "b1", "phone": PH, "bank_name": "x", "pan_prefix4": "6037", "pan_last4": "1234"}])
    with app.test_request_context(json={"amount": "۱۰۰۰۰۰۰۰", "bank_account_id": "b1", "client_request_id": "r1"}):
        from flask import session
        session["user_phone"] = PH
        resp = routes.withdrawals_request.__wrapped__() if hasattr(routes.withdrawals_request, "__wrapped__") else None
        if resp is None:
            pytest.skip("route decorator not unwrappable")
        body = resp.get_json()
        assert body["success"], body
    assert seen and all(depth == 0 for depth in seen)


def test_admin_paid_refused_when_commissions_cannot_cover_it(app, monkeypatch):
    """item 9."""
    from app.ai import admin_tools
    from app.utils import storage

    monkeypatch.setattr("app.express_partner.commission_sms.notify_partner_commission_txn", lambda **k: None)
    _seed(app, [{"id": 1, "partner_phone": PH, "commission_amount": 5_000_000, "status": "approved"}],
          [{"id": "w1", "phone": PH, "amount": 15_000_000, "status": "processing"}])
    with app.app_context():
        out = admin_tools._exec_withdrawal_status(withdrawal_id="w1", new_status="paid")
        assert not out["ok"] and out["allocation_short"] > 0
        assert storage.load_partner_withdrawals()[0]["status"] == "processing"
        assert storage.load_express_commissions()[0]["status"] == "approved"
