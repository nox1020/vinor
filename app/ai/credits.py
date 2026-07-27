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
        "max_assistant_history_chars": int(cfg.get("max_assistant_history_chars") or 300),
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

GUEST_LOGIN_URL = "/express/partner/home?menu=1"


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def guest_ai_limits_enabled() -> bool:
    """محدودیت پاسخ/گفتگو برای مهمان — پیش‌فرض روشن."""
    return _env_bool("VINOR_GUEST_AI_LIMITS_ENABLED", "1")


def guest_free_assistant_replies() -> int:
    """سقف پاسخ AI برای مهمان (پیش‌فرض ۳)."""
    if not guest_ai_limits_enabled():
        return 10**9
    raw = (os.environ.get("VINOR_GUEST_FREE_REPLIES") or "3").strip()
    try:
        return max(1, min(int(raw), 100))
    except ValueError:
        return 3


def guest_max_threads() -> int:
    """حداکثر گفتگوی هم‌زمان برای مهمان (پیش‌فرض ۱)."""
    if not guest_ai_limits_enabled():
        return 30
    raw = (os.environ.get("VINOR_GUEST_MAX_THREADS") or "1").strip()
    try:
        return max(1, min(int(raw), 5))
    except ValueError:
        return 1


def guest_login_error() -> str:
    n = guest_free_assistant_replies()
    if n >= 10**8:
        return "برای ادامه وارد شوید."
    return f"به سقف {n} پاسخ رسیدید. برای ادامه وارد شوید."


# سازگاری با importهای قدیمی
GUEST_FREE_ASSISTANT_REPLIES = guest_free_assistant_replies()
GUEST_LOGIN_ERROR = guest_login_error()


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


def get_last_balance_probe() -> dict[str, Any]:
    data = _load_cache()
    raw = (data.get("flags") or {}).get("last_balance_probe")
    return dict(raw) if isinstance(raw, dict) else {}


def _store_balance_probe(payload: dict[str, Any]) -> None:
    data = _load_cache()
    flags = data.setdefault("flags", {})
    flags["last_balance_probe"] = dict(payload or {})
    data["flags"] = flags
    _save_cache(data)


def probe_deepseek_api_balance(*, clear_on_ok: bool = True) -> dict[str, Any]:
    """استعلام زندهٔ موجودی از DeepSeek `/user/balance`."""
    import requests

    from app.keys import DEEPSEEK_BASE_URL, get_deepseek_api_key

    api_key = get_deepseek_api_key()
    if not api_key:
        out = {
            "ok": False,
            "error": "کلید API تنظیم نشده است.",
            "error_code": "no_api_key",
            "probed_at": time.time(),
        }
        _store_balance_probe(out)
        return out

    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/user/balance"
    try:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=25,
        )
    except requests.Timeout:
        out = {
            "ok": False,
            "error": "زمان استعلام موجودی به پایان رسید.",
            "error_code": "timeout",
            "probed_at": time.time(),
        }
        _store_balance_probe(out)
        return out
    except Exception as exc:
        out = {
            "ok": False,
            "error": f"خطای شبکه در استعلام موجودی: {exc}",
            "error_code": "network",
            "probed_at": time.time(),
        }
        _store_balance_probe(out)
        return out

    body: Any = {}
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {"raw": (resp.text or "")[:400]}

    probed_at = time.time()
    if resp.status_code == 402:
        mark_api_balance_depleted()
        out = {
            "ok": False,
            "depleted": True,
            "status_code": 402,
            "error": "موجودی API کافی نیست (402).",
            "error_code": "balance_depleted",
            "body": body if isinstance(body, dict) else {},
            "probed_at": probed_at,
        }
        _store_balance_probe(out)
        return out

    if resp.status_code == 401:
        out = {
            "ok": False,
            "status_code": 401,
            "error": "کلید API نامعتبر است.",
            "error_code": "unauthorized",
            "body": body if isinstance(body, dict) else {},
            "probed_at": probed_at,
        }
        _store_balance_probe(out)
        return out

    if not resp.ok:
        msg = ""
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or "").strip()
            msg = msg or str(body.get("message") or "").strip()
        out = {
            "ok": False,
            "status_code": resp.status_code,
            "error": msg or f"پاسخ ناموفق از DeepSeek ({resp.status_code})",
            "error_code": "api_error",
            "body": body if isinstance(body, dict) else {},
            "probed_at": probed_at,
        }
        _store_balance_probe(out)
        return out

    infos = []
    is_available = True
    if isinstance(body, dict):
        is_available = bool(body.get("is_available", True))
        raw_infos = body.get("balance_infos")
        if isinstance(raw_infos, list):
            for item in raw_infos:
                if not isinstance(item, dict):
                    continue
                infos.append(
                    {
                        "currency": str(item.get("currency") or ""),
                        "total_balance": str(item.get("total_balance") or ""),
                        "granted_balance": str(item.get("granted_balance") or ""),
                        "topped_up_balance": str(item.get("topped_up_balance") or ""),
                    }
                )

    if clear_on_ok and is_available:
        clear_api_balance_depleted()
    elif not is_available:
        mark_api_balance_depleted()

    out = {
        "ok": True,
        "depleted": not is_available,
        "is_available": is_available,
        "status_code": resp.status_code,
        "balances": infos,
        "body": body if isinstance(body, dict) else {},
        "probed_at": probed_at,
        "local_flag_cleared": bool(clear_on_ok and is_available),
    }
    _store_balance_probe(out)
    return out


# --- شیر اطمینان مصرف (Spend Fuse) ---
SPEND_FUSE_ERROR = (
    "مصرف هوش مصنوعی به‌خاطر سقف ایمنی قطع شده است. "
    "ادمین باید از پنل دوباره فعال کند."
)


def _spend_fuse_limits() -> dict[str, Any]:
    cfg = get_ai_settings()
    try:
        window = max(300, min(7 * 86400, int(cfg.get("spend_fuse_window_sec") or 86400)))
    except Exception:
        window = 86400
    try:
        max_tok = max(50_000, min(100_000_000, int(cfg.get("spend_fuse_max_tokens") or 2_500_000)))
    except Exception:
        max_tok = 2_500_000
    try:
        max_req = max(20, min(100_000, int(cfg.get("spend_fuse_max_requests") or 600)))
    except Exception:
        max_req = 600
    enabled = bool(cfg.get("spend_fuse_enabled", True))
    return {
        "enabled": enabled,
        "window_sec": window,
        "max_tokens": max_tok,
        "max_requests": max_req,
    }


def _roll_spend_window(spend: dict[str, Any], window_sec: int) -> dict[str, Any]:
    now = time.time()
    start = float(spend.get("window_start") or 0)
    if not start or (now - start) >= window_sec:
        return {
            "window_start": now,
            "tokens": 0,
            "requests": 0,
        }
    spend.setdefault("window_start", start)
    spend["tokens"] = int(spend.get("tokens") or 0)
    spend["requests"] = int(spend.get("requests") or 0)
    return spend


def spend_fuse_status() -> dict[str, Any]:
    """وضعیت شیر اطمینان برای پنل ادمین و ai_config."""
    limits = _spend_fuse_limits()
    data = _load_cache()
    flags = data.get("flags") or {}
    spend = _roll_spend_window(dict(data.get("spend") or {}), int(limits["window_sec"]))
    tripped = bool(flags.get("spend_fuse_tripped"))
    return {
        "enabled": bool(limits["enabled"]),
        "tripped": tripped,
        "tripped_at": float(flags.get("spend_fuse_tripped_at") or 0) or None,
        "reason": str(flags.get("spend_fuse_reason") or ""),
        "sms_sent": bool(flags.get("spend_fuse_sms_sent_at")),
        "window_sec": int(limits["window_sec"]),
        "max_tokens": int(limits["max_tokens"]),
        "max_requests": int(limits["max_requests"]),
        "used_tokens": int(spend.get("tokens") or 0),
        "used_requests": int(spend.get("requests") or 0),
        "window_started_at": float(spend.get("window_start") or 0) or None,
    }


def is_spend_fuse_tripped() -> bool:
    """اگر شیر خورده باشد، هر فراخوانی DeepSeek باید قطع شود."""
    limits = _spend_fuse_limits()
    if not limits["enabled"]:
        return False
    data = _load_cache()
    return bool((data.get("flags") or {}).get("spend_fuse_tripped"))


def clear_spend_fuse(*, reset_counters: bool = True) -> dict[str, Any]:
    """فعال‌سازی مجدد مصرف توسط ادمین."""
    data = _load_cache()
    flags = data.setdefault("flags", {})
    for key in (
        "spend_fuse_tripped",
        "spend_fuse_tripped_at",
        "spend_fuse_reason",
        "spend_fuse_sms_sent_at",
    ):
        flags.pop(key, None)
    data["flags"] = flags
    if reset_counters:
        data["spend"] = {
            "window_start": time.time(),
            "tokens": 0,
            "requests": 0,
        }
    _save_cache(data)
    try:
        current_app.logger.warning("AI spend fuse cleared by admin")
    except Exception:
        pass
    return spend_fuse_status()


def trip_spend_fuse(*, tokens: int, requests: int, max_tokens: int, max_requests: int) -> None:
    """قطع مصرف + پیامک یک‌بار به ادمین."""
    data = _load_cache()
    flags = data.setdefault("flags", {})
    already = bool(flags.get("spend_fuse_tripped"))
    reason = (
        f"سقف مصرف: {int(tokens):,} توکن / {int(max_tokens):,} "
        f"| {int(requests):,} درخواست / {int(max_requests):,}"
    )
    flags["spend_fuse_tripped"] = True
    flags["spend_fuse_tripped_at"] = time.time()
    flags["spend_fuse_reason"] = reason
    data["flags"] = flags
    _save_cache(data)
    if already and flags.get("spend_fuse_sms_sent_at"):
        return
    try:
        from app.ai.escalations import send_admin_spend_fuse_sms

        if send_admin_spend_fuse_sms(
            tokens=tokens,
            requests=requests,
            max_tokens=max_tokens,
            max_requests=max_requests,
        ):
            data = _load_cache()
            data.setdefault("flags", {})["spend_fuse_sms_sent_at"] = time.time()
            _save_cache(data)
    except Exception:
        try:
            current_app.logger.exception("AI spend fuse SMS failed")
        except Exception:
            pass
    try:
        current_app.logger.error("AI spend fuse TRIPPED | %s", reason)
    except Exception:
        pass


def record_spend_usage(*, prompt_tokens: int = 0, completion_tokens: int = 0) -> dict[str, Any]:
    """ثبت مصرف هر فراخوانی API؛ در صورت عبور از سقف، شیر را بزن."""
    limits = _spend_fuse_limits()
    if not limits["enabled"]:
        return spend_fuse_status()
    try:
        prompt_n = max(0, int(prompt_tokens or 0))
        completion_n = max(0, int(completion_tokens or 0))
    except Exception:
        prompt_n, completion_n = 0, 0
    added = prompt_n + completion_n
    data = _load_cache()
    spend = _roll_spend_window(dict(data.get("spend") or {}), int(limits["window_sec"]))
    spend["tokens"] = int(spend.get("tokens") or 0) + max(0, added)
    spend["requests"] = int(spend.get("requests") or 0) + 1
    data["spend"] = spend
    _save_cache(data)

    used_tok = int(spend["tokens"])
    used_req = int(spend["requests"])
    max_tok = int(limits["max_tokens"])
    max_req = int(limits["max_requests"])
    if used_tok >= max_tok or used_req >= max_req:
        trip_spend_fuse(
            tokens=used_tok,
            requests=used_req,
            max_tokens=max_tok,
            max_requests=max_req,
        )
    return spend_fuse_status()


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
    """اگر خیلی زود درخواست داده → پیام خطا (بدون API).

    همکار (partner): بدون فاصله اجباری — چت باید بلافاصله ارسال شود.
    """
    if not user_key:
        return None
    if audience == AUDIENCE_PARTNER:
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
    """هر پیام غیرخالی مجاز است (حتی ۱ کاراکتر مثل «۱»)."""
    if not (message or "").strip():
        return "پیام خالی است."
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
    if not is_guest_user_key(user_key) or not guest_ai_limits_enabled():
        return None
    limit = guest_free_assistant_replies()
    return max(0, limit - guest_assistant_reply_count(user_key))


def check_guest_login_required(user_key: str) -> dict[str, Any] | None:
    """اگر مهمان سقف پاسخ را تمام کرده → نیاز به ورود."""
    if not is_guest_user_key(user_key) or not guest_ai_limits_enabled():
        return None
    limit = guest_free_assistant_replies()
    used = guest_assistant_reply_count(user_key)
    if used < limit:
        return None
    return {
        "ok": False,
        "error": guest_login_error(),
        "need_login": True,
        "login_url": GUEST_LOGIN_URL,
        "guest_replies_used": used,
        "guest_replies_limit": limit,
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
            guest_free_assistant_replies(),
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

    guest_gate = check_guest_login_required(user_key)
    if guest_gate:
        return guest_gate

    if is_api_balance_depleted():
        return None

    if is_spend_fuse_tripped():
        return {
            "ok": False,
            "error": SPEND_FUSE_ERROR,
            "error_code": "spend_fuse",
            "spend_fuse": True,
        }

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
