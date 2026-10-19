# -*- coding: utf-8 -*-
"""پیشنهاد قیمت در cards فقط با offers_in_cards، بدون دوباره‌شماری تب معامله."""
from __future__ import annotations

import pytest

OWNER = "09121111000"
OFFER = {
    "id": "off-9",
    "negotiation_id": "neg-9",
    "land_code": "42",
    "amount": 250000000,
    "terms": "نقد",
    "status": "pending",
    "partner_phone": "09123333000",
    "buyer_phone": "09124444000",
    "proposed_by": "partner",
    "can_accept": True,
    "can_reject": True,
    "can_counter": True,
    "needs_action": True,
    "created_at": "2026-10-02T00:00:00Z",
    "updated_at": "2026-10-03T00:00:00Z",
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "unit-test-offer-cards")
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
    return application


def _profile():
    return {
        "phone": OWNER,
        "status": "approved",
        "partner_tier": "special",
        "plus_expires_at": "2099-01-01T00:00:00Z",
        "name": "پلاس",
    }


def _pipe(app, *, include=False):
    from app.express_partner.routes import _build_partner_sales_pipeline

    with app.app_context():
        return _build_partner_sales_pipeline(
            OWNER,
            _profile(),
            visit_rows=[],
            include_offers_in_cards=include,
        )


def test_offer_card_shape_matches_website_actions():
    from app.express_partner.special_offer_inbox import offer_pipeline_card

    card = offer_pipeline_card(OFFER)
    assert card["kind"] == "offer"
    assert card["pipeline_tab"] == "deals"
    assert card["id"] == "off-9"
    assert card["amount"] == 250000000
    assert card["terms"] == "نقد"
    assert card["status"] == "pending"
    assert card["partner_phone"] == "09123333000"
    assert card["can_accept"] is True
    assert card["can_reject"] is True
    assert card["can_counter"] is True
    assert card["title"] == "پیشنهاد قیمت · فایل 42"
    assert card["actions"] == {
        "accept": "/express/partner/inbox-offers/off-9/accept",
        "reject": "/express/partner/inbox-offers/off-9/reject",
        "counter": "/express/partner/inbox-offers/off-9/counter",
    }
    assert card["action_path"] == "/express/partner/inbox-offers/off-9/{action}"
    assert card["return_to"] == "visits"
    assert offer_pipeline_card({"id": ""})["id"] == ""


def test_offers_stay_out_of_cards_until_requested(app, monkeypatch):
    monkeypatch.setattr(
        "app.express_partner.special_offer_inbox.offers_for_special_owner",
        lambda _phone: [dict(OFFER)],
    )
    plain = _pipe(app, include=False)
    assert plain["offers"][0]["id"] == "off-9"
    assert all(card.get("kind") != "offer" for card in plain["cards"])
    assert plain["tab_counts"]["deals"] == 1

    folded = _pipe(app, include=True)
    offers_in_cards = [card for card in folded["cards"] if card.get("kind") == "offer"]
    assert len(offers_in_cards) == 1
    assert offers_in_cards[0]["pipeline_tab"] == "deals"
    assert folded["offers"][0]["id"] == "off-9"
    assert folded["tab_counts"]["deals"] == sum(
        1 for card in folded["cards"] if card.get("pipeline_tab") == "deals"
    )
    assert folded["tab_counts"]["deals"] == 1


def test_requests_payload_counts_deal_rows_once(app, monkeypatch):
    from app.express_partner.apk_native import requests_payload

    monkeypatch.setattr(
        "app.express_partner.special_offer_inbox.offers_for_special_owner",
        lambda _phone: [dict(OFFER)],
    )
    with app.app_context():
        hidden = requests_payload(OWNER, _profile(), offers_in_cards=False)
        shown = requests_payload(OWNER, _profile(), offers_in_cards=True)
    assert hidden["offers"][0]["amount"] == 250000000
    assert all(card.get("kind") != "offer" for card in hidden["cards"])
    assert hidden["tab_counts"]["deals"] == sum(
        1 for card in hidden["cards"] if card.get("pipeline_tab") == "deals"
    )
    kinds = [card.get("kind") for card in shown["cards"]]
    assert kinds.count("offer") == 1
    assert shown["tab_counts"]["deals"] == sum(
        1 for card in shown["cards"] if card.get("pipeline_tab") == "deals"
    )
    assert shown["offers"][0]["id"] == "off-9"


def test_offers_in_cards_query_is_opt_in(app):
    from app.express_partner.apk_native import offers_in_cards_param

    assert offers_in_cards_param("1") is True
    assert offers_in_cards_param("0") is False
    assert offers_in_cards_param(None) is False
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_phone"] = OWNER
    off = client.get("/express/partner/api/requests/data")
    on = client.get("/express/partner/api/requests/data?offers_in_cards=1")
    assert off.status_code == 200
    assert on.status_code == 200
    assert all(card.get("kind") != "offer" for card in off.get_json()["cards"])
    assert "offers" in on.get_json()
    assert on.get_json()["tab_counts"]["deals"] == sum(
        1 for card in on.get_json()["cards"] if card.get("pipeline_tab") == "deals"
    )
