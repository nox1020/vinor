# -*- coding: utf-8 -*-
"""Wallet item 1: admin withdrawal status change runs under the financial lock."""
from __future__ import annotations

import json
import threading

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    for k, v in {
        "INSTANCE_PATH": str(tmp_path), "SECRET_KEY": "unit-wallet-1", "SESSION_COOKIE_SECURE": "0",
        "VINOR_DISABLE_SMS_SCHEDULER": "1", "VINOR_DISABLE_REACH": "1", "VINOR_OPTIMIZATION_SCHEDULER": "0",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'v.db'}",
    }.items():
        monkeypatch.setenv(k, v)
    from app import create_app

    a = create_app()
    a.config.update(TESTING=True)
    return a


PH = "09124000123"


def _seed(app):
    from app.utils import storage

    with app.app_context():
        storage.save_express_commissions([{
            "id": 1, "partner_phone": PH, "commission_amount": 20_000_000, "status": "approved",
        }])
        storage.save_partner_withdrawals([{
            "id": "w1", "phone": PH, "amount": 15_000_000, "status": "pending",
        }])


def test_paid_updates_both_files_and_balance(app, monkeypatch):
    from app.ai import admin_tools
    from app.utils import storage
    from app.express_partner.partner_withdrawals import withdrawable_balance

    monkeypatch.setattr("app.express_partner.commission_sms.notify_partner_commission_txn", lambda **k: None)
    _seed(app)
    with app.app_context():
        assert admin_tools._exec_withdrawal_status(withdrawal_id="w1", new_status="approved")["ok"]
        assert admin_tools._exec_withdrawal_status(withdrawal_id="w1", new_status="paid")["ok"]
        comms, wds = storage.load_express_commissions(), storage.load_partner_withdrawals()
        assert wds[0]["status"] == "paid"
        assert withdrawable_balance(comms, wds, PH) == 5_000_000


def test_status_change_waits_for_the_financial_lock(app, monkeypatch):
    from app.ai import admin_tools
    from app.express_partner.deal_wallet import commission_store_lock
    from app.utils import storage

    monkeypatch.setattr("app.express_partner.commission_sms.notify_partner_commission_txn", lambda **k: None)
    _seed(app)
    done = threading.Event()

    def admin():
        with app.app_context():
            admin_tools._exec_withdrawal_status(withdrawal_id="w1", new_status="rejected")
        done.set()

    with app.app_context():
        with commission_store_lock():
            t = threading.Thread(target=admin)
            t.start()
            assert not done.wait(0.5), "admin change ran while another wallet mutation held the lock"
            # concurrent writer inside the lock: admin must see this, not overwrite it
            comms = storage.load_express_commissions()
            comms.append({"id": 2, "partner_phone": PH, "commission_amount": 1_000_000, "status": "approved"})
            storage.save_express_commissions(comms)
        t.join(5)
        assert done.is_set()
        ids = [c["id"] for c in storage.load_express_commissions()]
        assert 2 in ids
        assert storage.load_partner_withdrawals()[0]["status"] == "rejected"
