"""صرفه‌جویی اعتبار DeepSeek — محدودیت نرخ، کش پاسخ تکراری، تنظیمات بودجه."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from flask import current_app

from .audience import AUDIENCE_PARTNER
from .runtime_settings import get_ai_settings

from app.utils.storage import data_dir

# --- تنظیمات (قابل تغییر با متغیر محیطی) ---
def budget_config() -> dict[str, Any]:
    cfg = get_ai_settings()
    return {
        "min_interval_sec": float(cfg["min_interval_sec"]),
        "dedup_ttl_sec": int(cfg["dedup_ttl_sec"]),
        "max_history": int(cfg["max_history"]),
        "max_msg_chars": int(cfg["max_msg_chars"]),
        "max_assistant_history_chars": int(cfg.get("max_assistant_history_chars") or 420),
        "max_context_chars": int(cfg["max_context_chars"]),
        "max_tokens": int(cfg["max_tokens"]),
        "temperature": float(cfg["temperature"]),
        "public_ctx_ttl_sec": int(cfg["public_ctx_ttl_sec"]),
        "partner_ctx_ttl_sec": int(cfg["partner_ctx_ttl_sec"]),
        "min_message_chars": int(cfg["min_message_chars"]),
    }


def _cache_file() -> str:
    path = os.path.join(data_dir(), "ai_credit_cache.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _load_cache() -> dict[str, Any]:
    path = _cache_file()
    if not os.path.isfile(path):
        return {"rate": {}, "replies": {}, "flags": {}, "guest_replies": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("rate", {})
            data.setdefault("replies", {})
            data.setdefault("flags", {})
            data.setdefault("guest_replies", {})
            return data
    except Exception:
        pass
    return {"rate": {}, "replies": {}, "flags": {}, "guest_replies": {}}


BALANCE_SMS_COOLDOWN_SEC = 21600  # حداکثر یک پیامک هر ۶ ساعت

# مهمان بدون لاگین: تا این تعداد پاسخ؛ بعد الزام ورود
GUEST_FREE_ASSISTANT_REPLIES = 20
GUEST_LOGIN_URL = "/express/partner/home?menu=1"
GUEST_LOGIN_ERROR = "به سقف ۲۰ پاسخ رسیدید. برای ادامه وارد شوید."


def mark_api_balance_depleted() -> None:
    """پس از خطای 402 — جلوگیری از درخواست‌های بی‌فایده تا شارژ مجدد."""
    data = _load_cache()
    data.setdefault("flags", {})
    data["flags"]["api_balance_depleted"] = time.time()
    _save_cache(data)
    try:
        notify_admin_balance_sms_if_needed()
    except Exception:
        pass


def notify_admin_balance_sms_if_needed() -> bool:
    """پیامک اتمام موجودی DeepSeek به ادمین (با فاصلهٔ زمانی)."""
    data = _load_cache()
    flags = data.setdefault("flags", {})
    last = float(flags.get("balance_sms_sent_at") or 0)
    if last and (time.time() - last) < BALANCE_SMS_COOLDOWN_SEC:
        return False
    try:
        from app.ai.escalations import send_admin_balance_depleted_sms

        if not send_admin_balance_depleted_sms():
            return False
    except Exception:
        return False
    flags["balance_sms_sent_at"] = time.time()
    _save_cache(data)
    return True


def is_api_balance_depleted(max_age_sec: int = 604800) -> bool:
    """پیش‌فرض ۷ روز قفل — جلوگیری از اسپم 402 روی سرور تا شارژ مجدد."""
    data = _load_cache()
    ts = float((data.get("flags") or {}).get("api_balance_depleted") or 0)
    if not ts:
        return False
    return (time.time() - ts) < max_age_sec


def clear_api_balance_depleted() -> None:
    data = _load_cache()
    flags = data.get("flags") or {}
    flags.pop("api_balance_depleted", None)
    data["flags"] = flags
    _save_cache(data)


def _save_cache(data: dict[str, Any]) -> None:
    path = _cache_file()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        try:
            current_app.logger.warning("AI credit cache save failed: %s", exc)
        except Exception:
            pass


def _norm_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    t = re.sub(r"[؟?!.،,:;«»\"'()\[\]{}]", "", t)
    return t[:500]


def _user_scope(user_key: str, audience: str) -> str:
    return f"{audience}:{user_key}"


def _reply_cache_key(user_key: str, audience: str, message: str) -> str:
    base = _norm_text(message)
    if not base:
        return ""
    raw = f"{audience}|{user_key}|{base}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _prune_replies(store: dict[str, Any], ttl: int) -> None:
    now = time.time()
    replies = store.get("replies") or {}
    dead = [k for k, v in replies.items() if now - float(v.get("ts") or 0) > ttl]
    for k in dead:
        replies.pop(k, None)
    store["replies"] = replies


def check_rate_limit(user_key: str, audience: str) -> str | None:
    """اگر خیلی زود درخواست داده → پیام خطا (بدون API)."""
    if not user_key:
        return None
    cfg = budget_config()
    min_iv = cfg["min_interval_sec"]
    if min_iv <= 0:
        return None

    scope = _user_scope(user_key, audience)
    data = _load_cache()
    last = float((data.get("rate") or {}).get(scope) or 0)
    now = time.time()
    if last and (now - last) < min_iv:
        wait = int(min_iv - (now - last)) + 1
        return f"لطفاً {wait} ثانیه صبر کنید و دوباره بفرستید."
    return None


def record_api_call(user_key: str, audience: str) -> None:
    if not user_key:
        return
    data = _load_cache()
    data.setdefault("rate", {})
    data["rate"][_user_scope(user_key, audience)] = time.time()
    _save_cache(data)


def lookup_cached_reply(user_key: str, audience: str, message: str) -> dict[str, Any] | None:
    """پاسخ تکراری همان سوال — بدون فراخوانی API."""
    # پارتنر: کش فقط روی متن پیام است و ابزار/تاریخچه را نادیده می‌گیرد
    # (مثلاً «اولی» یا تکرار پیام بازدید → جواب غلط بدون کارت تأیید)
    if audience == AUDIENCE_PARTNER:
        return None
    key = _reply_cache_key(user_key, audience, message)
    if not key:
        return None
    cfg = budget_config()
    data = _load_cache()
    _prune_replies(data, cfg["dedup_ttl_sec"])
    hit = (data.get("replies") or {}).get(key)
    if not hit or not hit.get("reply"):
        return None
    return dict(hit)


def store_cached_reply(
    user_key: str,
    audience: str,
    message: str,
    result: dict[str, Any],
) -> None:
    if audience == AUDIENCE_PARTNER:
        return
    # پاسخ‌های وابسته به ابزار/کارت تأیید را کش نکن
    if result.get("agent_actions") or result.get("tool_land_codes"):
        return
    key = _reply_cache_key(user_key, audience, message)
    if not key or not result.get("reply"):
        return
    data = _load_cache()
    data.setdefault("replies", {})
    data["replies"][key] = {
        "reply": result.get("reply"),
        "land_codes": result.get("land_codes") or [],
        "escalated": bool(result.get("escalated")),
        "escalation_id": result.get("escalation_id") or "",
        "ts": time.time(),
    }
    _prune_replies(data, budget_config()["dedup_ttl_sec"])
    _save_cache(data)


def validate_message_length(message: str) -> str | None:
    cfg = budget_config()
    text = (message or "").strip()
    if len(_norm_text(text)) < cfg["min_message_chars"]:
        return "پیام خیلی کوتاه است."
    return None


def is_guest_user_key(user_key: str) -> bool:
    return str(user_key or "").startswith("guest_")


def _guest_usage_map(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.setdefault("guest_replies", {})
    if not isinstance(usage, dict):
        usage = {}
        data["guest_replies"] = usage
    return usage


def guest_assistant_reply_count(user_key: str) -> int:
    """سقف مصرف مهمان — max(کش پایدار، تاریخچهٔ چت قابل‌شمارش).

    کش مانع دور زدن سقف با پاک‌کردن گفتگو است؛ تاریخچه منبع به‌روز پاسخ‌هاست.
    """
    if not is_guest_user_key(user_key):
        return 0
    data = _load_cache()
    stored = int((_guest_usage_map(data).get(user_key) or 0))
    chat_count = 0
    try:
        from app.ai.audience import AUDIENCE_PUBLIC
        from app.ai.chat_store import count_assistant_replies

        chat_count = int(count_assistant_replies(user_key, audience=AUDIENCE_PUBLIC) or 0)
    except Exception:
        chat_count = 0
    used = max(stored, chat_count)
    # همگام‌سازی کش با واقعیت (بدون +۱ اضافه)
    if used != stored:
        _guest_usage_map(data)[user_key] = used
        _save_cache(data)
    return used


def guest_replies_remaining(user_key: str) -> int | None:
    if not is_guest_user_key(user_key):
        return None
    return max(0, GUEST_FREE_ASSISTANT_REPLIES - guest_assistant_reply_count(user_key))


def check_guest_login_required(user_key: str) -> dict[str, Any] | None:
    """اگر مهمان سقف پاسخ را تمام کرده → نیاز به ورود."""
    if not is_guest_user_key(user_key):
        return None
    used = guest_assistant_reply_count(user_key)
    if used < GUEST_FREE_ASSISTANT_REPLIES:
        return None
    return {
        "ok": False,
        "error": GUEST_LOGIN_ERROR,
        "need_login": True,
        "login_url": GUEST_LOGIN_URL,
        "guest_replies_used": used,
        "guest_replies_limit": GUEST_FREE_ASSISTANT_REPLIES,
        "guest_replies_remaining": 0,
    }


def record_guest_assistant_reply(user_key: str) -> int:
    """بعد از هر پاسخ موفق مهمان: شمارنده را حتماً یکی زیاد کن.

    منبع حقیقت = max(کش+۱، تعداد پاسخ در تاریخچه).
    +۱ تضمین می‌کند اگر شمارش تاریخچه خطا بدهد سقف قفل نشود/نامحدود نماند.
    """
    if not is_guest_user_key(user_key):
        return 0
    chat_count = 0
    try:
        from app.ai.audience import AUDIENCE_PUBLIC
        from app.ai.chat_store import count_assistant_replies

        chat_count = int(count_assistant_replies(user_key, audience=AUDIENCE_PUBLIC) or 0)
    except Exception:
        chat_count = 0
    data = _load_cache()
    usage = _guest_usage_map(data)
    stored = int(usage.get(user_key) or 0)
    n = max(stored + 1, chat_count)
    # سقف سخت — بیشتر از limit+buffer لازم نیست ولی برای anti-abuse نگه می‌داریم
    usage[user_key] = n
    _save_cache(data)
    try:
        from flask import current_app

        current_app.logger.info(
            "guest quota | user=%s used=%s chat=%s limit=%s",
            user_key,
            n,
            chat_count,
            GUEST_FREE_ASSISTANT_REPLIES,
        )
    except Exception:
        pass
    return n


def apply_credit_guard(
    user_key: str,
    audience: str,
    message: str,
) -> dict[str, Any] | None:
    """
    اگر نیازی به API نیست، نتیجه آماده برگردانده می‌شود.
    وگرنه None → ادامه به generate_reply.
    """
    err = validate_message_length(message)
    if err:
        return {"ok": False, "error": err}

    if is_api_balance_depleted():
        return None

    rate_err = check_rate_limit(user_key, audience)
    if rate_err:
        return {
            "ok": False,
            "error": rate_err,
            "rate_limited": True,
            "cached": False,
        }

    hit = lookup_cached_reply(user_key, audience, message)
    if hit:
        try:
            current_app.logger.info(
                "AI credit save: cached reply | user=%s | audience=%s",
                user_key,
                audience,
            )
        except Exception:
            pass
        return {
            "ok": True,
            "reply": hit.get("reply") or "",
            "land_codes": hit.get("land_codes") or [],
            "escalated": bool(hit.get("escalated")),
            "escalation_id": hit.get("escalation_id") or "",
            "cached": True,
            "meta": {"provider": "cache", "model": "dedup"},
        }
    return None
