# -*- coding: utf-8 -*-
"""Wallet invariants: privacy, available balance, concurrency, rollback."""
from __future__ import annotations
import threading
import time
import pytest
from flask import Flask

from app.express_partner.partner_bank_accounts import validate_new_account, apply_account_fields
from app.express_partner.partner_withdrawals import (
    MIN_WITHDRAWAL_AMOUNT, available_for_new_withdrawal, validate_new_request,
)
from app.express_partner.deal_wallet import commission_store_lock
import app.utils.storage as storage

PHONE = "09129994444"
AMOUNT = MIN_WITHDRAWAL_AMOUNT


def test_bank_saves_only_masked_pan_and_edit_does_not_need_pan():
    row, err = validate_new_account("mellat", "6037991234567890", "آزمایش بانکی", "")
    assert err is None
    assert "pan" not in row
    assert row["pan_prefix4"] == "6037" and row["pan_last4"] == "7890"
    changed, err = apply_account_fields(row, "melli", "", "صاحب حساب", "")
    assert err is None and changed["bank_key"] == "melli"
    assert "pan" not in changed
    assert changed["pan_last4"] == "7890"


def test_pending_withdrawal_reduces_available_balance():
    commissions = [{"partner_phone": PHONE, "status": "approved", "commission_amount": 30 * AMOUNT}]
    withdrawals = [{"phone": PHONE, "status": "pending", "amount": AMOUNT}]
    assert available_for_new_withdrawal(commissions, withdrawals, PHONE) == 29 * AMOUNT
    bank = {"id": "bank-1", "phone": PHONE, "bank_name": "ملت"}
    rejected, err = validate_new_request(30 * AMOUNT, "bank-1", PHONE, [bank], commissions, withdrawals)
    assert rejected is None and err == "insufficient_balance"
    accepted, err = validate_new_request(AMOUNT, "bank-1", PHONE, [bank], commissions, withdrawals)
    assert err is None and accepted["amount"] == AMOUNT


def test_financial_lock_serializes_threads(tmp_path):
    app = Flask("wallet-guard-test", instance_path=str(tmp_path))
    values = []
    state = {"n": 0}
    def worker():
        with commission_store_lock(app):
            before = state["n"]
            time.sleep(0.005)
            state["n"] = before + 1
            values.append(state["n"])
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert sorted(values) == list(range(1, 9))


def test_financial_pair_rolls_back_failed_second_write(tmp_path, monkeypatch):
    app = Flask("wallet-storage-test", instance_path=str(tmp_path))
    with app.app_context():
        storage.save_express_commissions([{"id": 1, "commission_amount": 30}])
        storage.save_partner_withdrawals([{"id": "old", "amount": 10}])
        real_save = storage.save_partner_withdrawals
        state = {"failed": False}
        def fail_once(*args, **kwargs):
            if not state["failed"]:
                state["failed"] = True
                raise OSError("disk failure")
            return real_save(*args, **kwargs)
        monkeypatch.setattr(storage, "save_partner_withdrawals", fail_once)
        with pytest.raises(OSError):
            storage.save_financial_pair([{"id": 1, "commission_amount": 20}],
                                        [{"id": "new", "amount": 20}])
        assert storage.load_express_commissions()[0]["commission_amount"] == 30
        assert storage.load_partner_withdrawals()[0]["id"] == "old"


def test_loading_legacy_bank_accounts_removes_full_pan(tmp_path):
    app = Flask("bank-privacy-test", instance_path=str(tmp_path))
    with app.app_context():
        path = storage.ensure_file("EXPRESS_PARTNER_BANK_ACCOUNTS_FILE",
                                   "express_partner_bank_accounts.json", [], app)
        storage._save(path, [{"id": "old", "pan": "6037991234567890",
                              "pan_prefix4": "6037", "pan_last4": "7890"}])
        result = storage.load_partner_bank_accounts()
        assert "pan" not in result[0]
        assert "pan" not in storage._load(path)[0]



def test_interrupted_wallet_save_is_recovered_from_redo_journal(tmp_path):
    app = Flask("wallet-recovery-test", instance_path=str(tmp_path))
    with app.app_context():
        storage.save_express_commissions([{"id": 1, "commission_amount": 30}])
        storage.save_partner_withdrawals([{"id": "old", "amount": 10}])
        journal = storage._financial_journal_path()
        storage._save(journal, {
            "commissions": [{"id": 1, "commission_amount": 20}],
            "withdrawals": [{"id": "new", "amount": 20}],
        })
        assert storage.load_express_commissions()[0]["commission_amount"] == 20
        assert storage.load_partner_withdrawals()[0]["id"] == "new"
        assert not __import__("os").path.exists(journal)
