# -*- coding: utf-8 -*-
"""خلاصهٔ حافظهٔ زندهٔ Partner — مثل Memory در ChatGPT؛ هر بار با مدل بازنویسی می‌شود."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from flask import current_app

_MEMORY_SYSTEM = """تو نویسندهٔ «حافظهٔ کاربر» هستی؛ درست مثل Memory در ChatGPT.
فقط فارسی بنویس. ۳ تا ۶ جمله یا بولت کوتاه و پایدار.
حقایق مهم دربارهٔ این شخص را نگه دار و با اطلاعات جدید ادغام/بازنویسی کن:
نام، نقش، شهر، ترجیح‌ها، فایل‌های در حال پیگیری، بازدید/معامله، عادت فروش، نکات مفید بعدی.
آمار خام و لیست KPI را کپی نکن؛ به زبان طبیعی بنویس.
عنوان نگذار، نگو «حافظه:»، فقط متن حافظه."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def _memory_dir() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "instance")
        )
    path = os.path.join(base, "data", "ai_memory", "partner_live")
    os.makedirs(path, exist_ok=True)
    return path


def _path_for(phone: str) -> str:
    ph = _norm_phone(phone)
    if not ph:
        return ""
    return os.path.join(_memory_dir(), f"{ph}.json")


def load_partner_live_memory(phone: str) -> dict[str, Any]:
    path = _path_for(phone)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_partner_live_memory(
    phone: str,
    *,
    summary: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = _path_for(phone)
    if not path:
        return {}
    row: dict[str, Any] = {
        "phone": _norm_phone(phone),
        "summary": (summary or "").strip(),
        "updated_at": _now_iso(),
        "source": "llm",
    }
    if isinstance(meta, dict) and meta:
        row["meta"] = meta
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(row, f, ensure_ascii=False, indent=2)
    except Exception:
        try:
            current_app.logger.warning("partner live memory save failed | %s", path)
        except Exception:
            pass
    return row


def _collect_facts(phone: str) -> dict[str, Any]:
    """حقایق خام برای ورودی مدل — خودشان خلاصهٔ نمایشی نیستند."""
    ph = _norm_phone(phone)
    facts: dict[str, Any] = {"phone": ph}
    try:
        from app.express_partner.routes import (
            _find_partner_record,
            _is_partner_approved,
            _is_partner_special,
            _partner_commission_stats,
            _commissions_for_phone,
            _canonical_partner_phone,
        )
        from app.utils.storage import load_express_partners

        partners = load_express_partners() or []
        profile = _find_partner_record(partners, ph) or {"phone": ph}
        name = str((profile or {}).get("name") or "").strip()
        city = str((profile or {}).get("city") or "").strip()
        bio = str((profile or {}).get("bio") or "").strip()
        approved = bool(_is_partner_approved(profile))
        special = bool(_is_partner_special(profile)) if approved else False
        role = "بازاریاب ویژه" if special else ("بازاریاب فروش" if approved else "کاربر عادی")
        facts["name"] = name or "—"
        facts["role"] = role
        facts["city"] = city or "—"
        if bio:
            facts["bio"] = bio[:200]
        try:
            stats = _partner_commission_stats(ph, _commissions_for_phone(ph))
            facts["wallet_withdrawable"] = int(stats.get("withdrawable_balance") or 0)
            facts["commission_pending"] = int(stats.get("pending_amount") or 0)
        except Exception:
            pass
        try:
            from app.express_partner.visit_requests import (
                APPROVED_STATUS,
                DONE_PENDING_STATUS,
                PENDING_STATUS,
                load_express_visit_requests,
            )

            open_st = frozenset({PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS})
            visits = load_express_visit_requests() or []
            facts["open_visits"] = sum(
                1
                for r in visits
                if isinstance(r, dict)
                and _canonical_partner_phone(str(r.get("partner_phone") or "")) == ph
                and str(r.get("status") or "").strip() in open_st
            )
        except Exception:
            pass
        try:
            from app.express_partner.partner_missions import get_active_mission

            mission = get_active_mission(ph) if approved else None
            if mission:
                facts["active_file"] = str(mission.get("land_code") or "").strip()
                facts["active_stage"] = str(mission.get("stage_label") or "").strip()
        except Exception:
            pass
    except Exception:
        pass

    # چند پیام اخیر چت
    try:
        from app.ai.audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
        from app.ai.chat_store import ensure_active_thread, messages_for_ui

        aud = AUDIENCE_PARTNER
        try:
            from app.express_partner.routes import _find_partner_record, _is_partner_approved
            from app.utils.storage import load_express_partners

            prof = _find_partner_record(load_express_partners() or [], ph)
            if not _is_partner_approved(prof):
                aud = AUDIENCE_PUBLIC
        except Exception:
            pass
        tid = ensure_active_thread(ph, audience=aud)
        msgs = messages_for_ui(ph, thread_id=tid, audience=aud) or []
        recent: list[dict[str, str]] = []
        for m in msgs[-8:]:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip()
            content = str(m.get("content") or "").strip()
            if role in ("user", "assistant") and content and not m.get("hide_ui"):
                recent.append({"role": role, "content": content[:220]})
        if recent:
            facts["recent_chat"] = recent
    except Exception:
        pass

    # منبع حقیقت ساخت‌یافته: ai_memory
    try:
        from app.memory.service import list_memory_brief

        brief = list_memory_brief(ph, limit=8)
        if brief:
            facts["ai_memory"] = [
                str(row.get("value") or "").strip()
                for row in brief
                if str(row.get("value") or "").strip()
            ]
    except Exception:
        pass
    return facts


def _llm_rewrite_summary(
    *,
    previous: str,
    facts: dict[str, Any],
    last_user: str = "",
    last_assistant: str = "",
    action_note: str = "",
) -> str:
    from app.ai.services import _call_deepseek

    payload = {
        "حافظه_قبلی": previous or "(خالی)",
        "حقایق_سیستم": facts,
        "آخرین_پیام_کاربر": (last_user or "")[:300],
        "آخرین_پاسخ_وینور": (last_assistant or "")[:400],
        "آخرین_اقدام": (action_note or "")[:200],
    }
    user_msg = (
        "با این ورودی، حافظهٔ کاربر را از نو بنویس (ادغام با حافظهٔ قبلی):\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    out = _call_deepseek(
        [
            {"role": "system", "content": _MEMORY_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        tools=None,
        max_tokens=280,
        temperature=0.35,
    )
    if not out.get("ok"):
        return ""
    text = str(out.get("reply") or "").strip()
    # پاک‌سازی حداقلی
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"^(حافظه|Memory)\s*[:：]\s*", "", text, flags=re.I).strip()
    if len(text) > 1200:
        text = text[:1199].rstrip() + "…"
    return text


def rewrite_partner_live_memory(
    phone: str,
    *,
    last_user: str = "",
    last_assistant: str = "",
    action_note: str = "",
) -> dict[str, Any]:
    """ارسال به مدل و بازنویسی خلاصهٔ حافظه مثل GPT Memory."""
    ph = _norm_phone(phone)
    if not ph:
        return {}
    prev_row = load_partner_live_memory(ph)
    previous = str((prev_row or {}).get("summary") or "").strip()
    # اگر قبلی فقط کپی KPI بود، خالی در نظر بگیر تا مدل از نو بنویسد
    if previous and previous.count("فایل باز") and "آخرین" in previous and len(previous) < 220:
        previous = ""
    facts = _collect_facts(ph)
    summary = ""
    try:
        summary = _llm_rewrite_summary(
            previous=previous,
            facts=facts,
            last_user=last_user,
            last_assistant=last_assistant,
            action_note=action_note,
        )
    except Exception as exc:
        try:
            current_app.logger.warning("partner memory LLM failed: %s", exc)
        except Exception:
            pass
    if not summary:
        # fallback کوتاه — نه کپی KPI
        name = str(facts.get("name") or "").strip()
        role = str(facts.get("role") or "").strip()
        bits = []
        if name and name != "—":
            bits.append(f"{name} ({role})" if role else name)
        elif role:
            bits.append(role)
        if last_user:
            bits.append(f"آخرین موضوع گفتگو: {last_user[:100]}")
        if action_note:
            bits.append(f"آخرین اقدام: {action_note[:100]}")
        summary = "\n".join(bits).strip() or "هنوز حافظه‌ای ساخته نشده — با چت بعدی پر می‌شود."
    row = save_partner_live_memory(
        ph,
        summary=summary,
        meta={"facts_keys": list(facts.keys()), "source": "llm" if summary else "fallback"},
    )
    # همگام با منبع حقیقت ai_memory
    try:
        from app.memory.service import upsert_live_summary

        upsert_live_summary(ph, summary)
    except Exception:
        pass
    return row
