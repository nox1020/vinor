# -*- coding: utf-8 -*-
"""Chat intro and signup copy are not limited to one village."""
from __future__ import annotations

from pathlib import Path


def test_public_welcome_asks_about_buying_without_a_village():
    from app.ai.welcome import opening_text

    text = opening_text()
    assert "دنبال خرید ملکی" in text
    assert "گرمابسرد" not in text


def test_goal_and_compact_rule_name_every_city():
    from app.ai.config import _COMMON_RULES, _COMMON_RULES_COMPACT
    from app.ai.goal import GEO_SCOPE_FA, GOAL_SYSTEM

    assert GEO_SCOPE_FA == "همهٔ شهرها"
    assert "گرمابسرد" not in GOAL_SYSTEM
    assert "گرمابسرد" not in _COMMON_RULES
    assert "محدوده: همهٔ شهرها" in _COMMON_RULES_COMPACT


def test_cooperation_info_does_not_lock_one_village():
    from app.ai.agent_tools import _tool_coop_info

    facts = _tool_coop_info({"topic": "terms"})["model_result"]["facts"]["terms"]
    assert "گرمابسرد" not in facts
    assert "همهٔ شهرها" in facts
    assert "فقط" not in facts


def test_blank_listing_city_is_unknown(monkeypatch):
    monkeypatch.setattr(
        "app.ai.agent_tools.accessible_lands_map",
        lambda phone, aud: {
            "9": {"code": "9", "title": "زمین بدون شهر", "city": "", "_is_public": True}
        },
    )
    monkeypatch.setattr("app.ai.context._select_lands_by_rag", lambda *args, **kwargs: [])
    from app.ai.agent_tools import _tool_search_lands

    found = _tool_search_lands(
        {"query": "زمین", "limit": 2},
        phone="09120000000",
        audience="public",
    )
    assert found["model_result"]["lands"][0]["city"] == "نامشخص"
    assert found["model_result"]["service_area"] == "همهٔ شهرها"
    assert "گرمابسرد" not in str(found["model_result"])


def test_signup_keeps_another_city_and_does_not_invent_one():
    from app.express_partner.routes import _default_apply_city
    from app.utils.iran_cities import is_allowed_service_city, is_plausible_city_name

    assert _default_apply_city("") == ""
    assert _default_apply_city("کرج") == "کرج"
    assert _default_apply_city("!!!") == ""
    assert is_plausible_city_name("اصفهان") is True
    assert is_allowed_service_city("اصفهان") is True
    assert is_allowed_service_city("!") is False


def test_web_chat_welcome_is_general_persian():
    page = Path("app/express_partner/templates/express_partner/ai.html").read_text(
        encoding="utf-8"
    )
    assert "دنبال خرید ملکی" in page
    assert "گرمابسرد" not in page
    assert "ط³ظ„ط§ظ…" not in page
