# -*- coding: utf-8 -*-
"""قرارداد کارت: یک اقدام اصلی، بدون حدس، و نوبت پیشنهاد."""
from __future__ import annotations

from datetime import datetime

from app.express_partner.follow_card_contract import build_follow_contract, offer_contract, sort_follow_cards


def test_marketer_attendance_waits_for_the_visit_time():
    early = build_follow_contract({
        "id": "v",
        "direction": "outgoing",
        "status": "approved",
        "visit_date": "2026-11-11",
        "visit_time": "18:00",
    }, now=datetime(2026, 11, 11, 9, 0))
    assert early["primary_action"] is None
    assert "زمان بازدید" in early["disabled_reason"]
    opened = build_follow_contract({
        "id": "v",
        "direction": "outgoing",
        "status": "approved",
        "visit_date": "2026-11-11",
        "visit_time": "09:00",
    }, now=datetime(2026, 11, 11, 9, 5))
    assert opened["primary_action"]["label"] == "بازدید انجام شد"
    assert opened["danger_actions"][0]["label"] == "مشتری نیامد"


def test_owner_interested_has_only_sale_confirm_and_shortfall_is_one_action():
    interested = build_follow_contract({
        "id": "v",
        "direction": "incoming",
        "status": "completed",
        "visit_outcome": "interested",
        "can_confirm_deal": True,
        "marketer_name": "سارا",
    })
    assert interested["primary_action"]["id"] == "confirm_sale"
    assert interested["danger_actions"] == []
    short = build_follow_contract({
        "id": "v",
        "direction": "incoming",
        "status": "completed",
        "deal_decision": "approved",
        "tx_status": "in_transaction",
        "deal_commission_amount": 50000,
        "wallet_shortfall": 10000,
        "wallet_charge_path": "/express/partner/wallet/charge",
        "listing_hold": 20000,
        "marketer_name": "سارا",
    })
    assert short["primary_action"]["id"] == "cover_shortfall"
    assert short["primary_action"]["method"] == "GET"
    assert short["danger_actions"] == []


def test_result_has_no_default_and_closed_names_the_amount():
    result = build_follow_contract({
        "id": "v",
        "direction": "outgoing",
        "status": "completed",
    })
    assert result["primary_action"]["id"] == "record_result"
    assert result["primary_action"]["body"]["default"] == ""
    closed = build_follow_contract({
        "id": "v",
        "direction": "outgoing",
        "status": "completed",
        "deal_decision": "closed",
        "deal_commission_amount": 25000,
    })
    assert "25000" in closed["status_label"]
    assert closed["secondary_actions"][0]["id"] == "view_receipt"
    assert closed["primary_action"] is None


def test_sort_puts_my_action_before_overdue_then_latest():
    cards = [
        {"id": "old", "updated_at": "2026-01-01", "contract": {}},
        {"id": "late", "updated_at": "2026-01-02", "deal_overdue": True, "contract": {}},
        {"id": "mine", "updated_at": "2026-01-01", "contract": {"needs_my_action": True}},
    ]
    assert [card["id"] for card in sort_follow_cards(cards)] == ["mine", "late", "old"]


def test_offer_turn_comes_from_proposed_by():
    mine = offer_contract({"id": "o", "proposed_by": "partner", "amount": 10})
    assert mine["your_turn"] is True
    assert mine["primary_action"]["id"] == "accept_offer"
    assert mine["danger_actions"][0]["confirmation"]
    theirs = offer_contract({"id": "o", "proposed_by": "special", "amount": 10})
    assert theirs["your_turn"] is False
    assert theirs["primary_action"] is None
    assert theirs["disabled_reason"]
