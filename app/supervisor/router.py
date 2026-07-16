from __future__ import annotations

import re

from app.supervisor.interfaces import (
    ROUTE_FAQ,
    ROUTE_FOLLOW_UP,
    ROUTE_GENERAL_CHAT,
    ROUTE_GREETING,
    ROUTE_PARTNER_OPS,
    ROUTE_PROPERTY_COMPARE,
    ROUTE_PROPERTY_SEARCH,
    Router,
    SupervisorRequest,
)

_GREETING_RE = re.compile(
    r"^(سلام|درود|صبح بخیر|عصر بخیر|شب بخیر|hi|hello|hey)([\s!.،]?)*$",
    re.I,
)
_COMPARE_RE = re.compile(r"(مقایسه|بین این|کدام بهتر|فرق)", re.I)
_SEARCH_RE = re.compile(
    r"(ویلا|زمین|باغ|ملک|فایل|پیدا|جستجو|گرمابسرد|دماوند|بودجه|میلیارد|میلیون)",
    re.I,
)
_FAQ_RE = re.compile(
    r"(همکاری|پورسانت|شرایط|سطوح|چطور همکار|وضعیت درخواست|قوانین)",
    re.I,
)
_FOLLOW_RE = re.compile(r"(بعدی|کار بعدی|چی کار کنم|ادامه|پیگیری|همون|همین فایل)", re.I)
_OPS_INTENTS = frozenset(
    {"visit", "complete_visit", "deal", "release", "marketing", "coop_apply"}
)


class RuleRouter(Router):
    """Rule-based intent routing — no LLM."""

    def route(self, req: SupervisorRequest) -> str:
        intent = (req.chip_intent or "").strip().lower()
        msg = (req.message or "").strip()

        if intent in _OPS_INTENTS:
            return ROUTE_PARTNER_OPS
        if intent == "find_land":
            return ROUTE_PROPERTY_SEARCH
        if intent == "next_action":
            return ROUTE_FOLLOW_UP
        if intent.startswith("coop_"):
            return ROUTE_FAQ

        if not msg or _GREETING_RE.match(msg):
            return ROUTE_GREETING
        if _COMPARE_RE.search(msg):
            return ROUTE_PROPERTY_COMPARE
        if _FAQ_RE.search(msg):
            return ROUTE_FAQ
        if _FOLLOW_RE.search(msg):
            return ROUTE_FOLLOW_UP
        if _SEARCH_RE.search(msg):
            return ROUTE_PROPERTY_SEARCH
        return ROUTE_GENERAL_CHAT
