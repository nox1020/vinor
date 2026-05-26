"""صرفه‌جویی اعتبار DeepSeek — محدودیت نرخ، کش پاسخ تکراری، تنظیمات بودجه."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from flask import current_app

from app.utils.storage import data_dir

# --- تنظیمات (قابل تغییر با متغیر محیطی) ---
def budget_config() -> dict[str, Any]:
    return {
        "min_interval_sec": float(os.environ.get("VINOR_AI_MIN_INTERVAL_SEC", "4")),
        "dedup_ttl_sec": int(os.environ.get("VINOR_AI_DEDUP_TTL_SEC", "180")),
        "max_history": int(os.environ.get("VINOR_AI_MAX_HISTORY", "12")),
        "max_msg_chars": int(os.environ.get("VINOR_AI_MAX_MSG_CHARS", "2500")),
        "max_context_chars": int(os.environ.get("VINOR_AI_MAX_CONTEXT_CHARS", "9000")),
        "max_tokens": int(os.environ.get("VINOR_AI_MAX_TOKENS", "1024")),
        "temperature": float(os.environ.get("VINOR_AI_TEMPERATURE", "0.5")),
        "public_ctx_ttl_sec": int(os.environ.get("VINOR_AI_PUBLIC_CTX_TTL", "300")),
        "partner_ctx_ttl_sec": int(os.environ.get("VINOR_AI_PARTNER_CTX_TTL", "120")),
        "min_message_chars": int(os.environ.get("VINOR_AI_MIN_MESSAGE_CHARS", "2")),
    }


def _cache_file() -> str:
    path = os.path.join(data_dir(), "ai_credit_cache.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _load_cache() -> dict[str, Any]:
    path = _cache_file()
    if not os.path.isfile(path):
        return {"rate": {}, "replies": {}, "flags": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("rate", {})
            data.setdefault("replies", {})
            data.setdefault("flags", {})
            return data
    except Exception:
        pass
    return {"rate": {}, "replies": {}, "flags": {}}


def mark_api_balance_depleted() -> None:
    """پس از خطای 402 — جلوگیری از درخواست‌های بی‌فایده تا شارژ مجدد."""
    data = _load_cache()
    data.setdefault("flags", {})
    data["flags"]["api_balance_depleted"] = time.time()
    _save_cache(data)


def is_api_balance_depleted(max_age_sec: int = 86400) -> bool:
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
