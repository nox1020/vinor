from __future__ import annotations

import re

from app.conversation.interfaces import (
    INTENT_BECOME_PARTNER,
    INTENT_COMPARE,
    INTENT_DEAL,
    INTENT_EDIT_PROPERTY,
    INTENT_GENERAL,
    INTENT_NEGOTIATION,
    INTENT_RECOMMENDATION,
    INTENT_REGISTER_PROPERTY,
    INTENT_SEARCH,
    INTENT_SUPPORT,
    INTENT_VISIT,
    IntentInfo,
    IntentResolver,
)

_CHIP_MAP = {
    "visit": INTENT_VISIT,
    "complete_visit": INTENT_VISIT,
    "deal": INTENT_DEAL,
    "release": INTENT_DEAL,
    "coop_apply": INTENT_BECOME_PARTNER,
    "find_land": INTENT_SEARCH,
    "marketing": INTENT_REGISTER_PROPERTY,
    "edit_property": INTENT_EDIT_PROPERTY,
}

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (INTENT_VISIT, re.compile(r"(بازدید|وقت بازدید|ثبت بازدید)", re.I)),
    (INTENT_DEAL, re.compile(r"(معامله|فروش نهایی|ثبت معامله|قولنامه)", re.I)),
    (INTENT_BECOME_PARTNER, re.compile(r"(همکار شو|درخواست همکاری|شروع همکاری|ارتقا به همکار)", re.I)),
    (INTENT_EDIT_PROPERTY, re.compile(r"(ویرایش ملک|ویرایش فایل|اصلاح فایل|تغییر قیمت فایل)", re.I)),
    (INTENT_REGISTER_PROPERTY, re.compile(r"(ثبت ملک|آگهی کن|ثبت فایل|ملک ثبت)", re.I)),
    (INTENT_RECOMMENDATION, re.compile(r"(پیشنهاد|بهترین|توصیه|مناسب.?من)", re.I)),
    (INTENT_COMPARE, re.compile(r"(مقایسه|کدام بهتر|فرق)", re.I)),
    (INTENT_NEGOTIATION, re.compile(r"(مذاکره|چانه|تخفیف|قیمت نهایی)", re.I)),
    (INTENT_SUPPORT, re.compile(r"(پشتیبانی|مشکل|شکایت|کمک لازم|تیکت)", re.I)),
    (INTENT_SEARCH, re.compile(r"(ویلا|زمین|باغ|ملک|فایل|پیدا|جستجو|بودجه)", re.I)),
]


class RuleIntentResolver(IntentResolver):
    def resolve(self, *, message: str, chip_intent: str = "") -> IntentInfo:
        chip = (chip_intent or "").strip().lower()
        if chip in _CHIP_MAP:
            return IntentInfo(intent=_CHIP_MAP[chip], confidence=0.95, reason=f"chip:{chip}")
        msg = (message or "").strip()
        if not msg:
            return IntentInfo(intent=INTENT_GENERAL, confidence=0.9, reason="empty")
        for intent, pat in _PATTERNS:
            if pat.search(msg):
                return IntentInfo(intent=intent, confidence=0.8, reason=f"rule:{intent}")
        return IntentInfo(intent=INTENT_GENERAL, confidence=0.6, reason="default")
