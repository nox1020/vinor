# -*- coding: utf-8 -*-
"""تنظیمات درگاه زرین‌پال برای Vinor Plus (settings.json → zarinpal)."""
from __future__ import annotations

import os
from typing import Any

DEFAULT_DESCRIPTION = "اشتراک Vinor Plus — وینور"

# مدت پیش‌فرض اشتراک پس از هر پرداخت موفق
DEFAULT_SUBSCRIPTION_DAYS = 30

# در sandbox زرین‌پال می‌توان هر UUID معتبر استفاده کرد (مستندات رسمی).
SANDBOX_DEFAULT_MERCHANT_ID = "00000000-0000-4000-8000-000000000001"


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def zarinpal_plus_feature_enabled() -> bool:
    """فلگ env — پیش‌فرض روشن. برای قطع اضطراری بدون پنل."""
    return _env_bool("VINOR_ZARINPAL_PLUS_ENABLED", "1")


def plus_system_enabled() -> bool:
    """
    Master کل سیستم پرداخت + Vinor Plus سمت کاربر/همکار.
    env (VINOR_ZARINPAL_PLUS_ENABLED، پیش‌فرض روشن) AND settings.zarinpal.enabled.

    پیش‌فرض settings وقتی کلید غایب است: خاموش (False).
    اگر در settings.json مقدار true ذخیره شده باشد، همان می‌ماند.
    """
    if not zarinpal_plus_feature_enabled():
        return False
    try:
        return bool(get_zarinpal_settings().get("enabled", False))
    except Exception:
        return False


def zarinpal_payment_primary() -> bool:
    """
    اگر روشن باشد، CTA صفحهٔ پلاس مستقیم به درگاه می‌رود.
    اگر خاموش باشد، همان مسیر قدیمی request_plus (SMS به ادمین) استفاده می‌شود.
    """
    if not plus_system_enabled():
        return False
    return _env_bool("VINOR_ZARINPAL_PLUS_PAYMENT_PRIMARY", "1")


def default_zarinpal_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "merchant_id": (os.environ.get("ZARINPAL_MERCHANT_ID") or "").strip(),
        "sandbox": True,
        "amount_toman": 990_000,
        "subscription_days": DEFAULT_SUBSCRIPTION_DAYS,
        "callback_url": "",
        "description": DEFAULT_DESCRIPTION,
        "partner_sms_enabled": True,
        "sms_activation_message": "",
        "sms_renewal_message": "",
        "sms_expiry_reminder_message": "",
        "sms_expired_message": "",
    }


def _coerce(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = default_zarinpal_settings()
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw and raw["enabled"] is not None:
        if isinstance(raw["enabled"], bool):
            out["enabled"] = raw["enabled"]
        else:
            out["enabled"] = str(raw["enabled"]).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
    mid = str(raw.get("merchant_id") or "").strip()
    if mid:
        out["merchant_id"] = mid
    if "sandbox" in raw and raw["sandbox"] is not None:
        if isinstance(raw["sandbox"], bool):
            out["sandbox"] = raw["sandbox"]
        else:
            out["sandbox"] = str(raw["sandbox"]).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
    try:
        if raw.get("amount_toman") is not None and str(raw.get("amount_toman")).strip() != "":
            out["amount_toman"] = max(0, int(raw["amount_toman"]))
    except (TypeError, ValueError):
        pass
    try:
        if raw.get("subscription_days") is not None and str(raw.get("subscription_days")).strip() != "":
            out["subscription_days"] = max(1, int(raw["subscription_days"]))
    except (TypeError, ValueError):
        pass
    cb = str(raw.get("callback_url") or "").strip()
    if cb:
        out["callback_url"] = cb
    desc = str(raw.get("description") or "").strip()
    if desc:
        out["description"] = desc
    if "partner_sms_enabled" in raw and raw["partner_sms_enabled"] is not None:
        if isinstance(raw["partner_sms_enabled"], bool):
            out["partner_sms_enabled"] = raw["partner_sms_enabled"]
        else:
            out["partner_sms_enabled"] = str(raw["partner_sms_enabled"]).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
    for key in (
        "sms_activation_message",
        "sms_renewal_message",
        "sms_expiry_reminder_message",
        "sms_expired_message",
    ):
        if raw.get(key) is not None:
            out[key] = str(raw.get(key) or "").strip()
    return out


def get_zarinpal_settings() -> dict[str, Any]:
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get("zarinpal")
    except Exception:
        stored = None
    cfg = _coerce(stored if isinstance(stored, dict) else None)
    env_mid = (os.environ.get("ZARINPAL_MERCHANT_ID") or "").strip()
    if env_mid:
        cfg["merchant_id"] = env_mid
    env_sandbox = (os.environ.get("ZARINPAL_SANDBOX") or "").strip().lower()
    if env_sandbox in ("0", "false", "no", "off"):
        cfg["sandbox"] = False
    elif env_sandbox in ("1", "true", "yes", "on"):
        cfg["sandbox"] = True
    if not zarinpal_plus_feature_enabled():
        cfg["enabled"] = False
    return cfg


def save_zarinpal_settings(patch: dict[str, Any]) -> dict[str, Any]:
    import json

    from app.utils.storage import _SETTINGS_CACHE, ensure_file, load_settings

    current = dict(load_settings() or {})
    merged = _coerce(current.get("zarinpal") if isinstance(current.get("zarinpal"), dict) else None)
    if "enabled" in patch:
        merged["enabled"] = bool(patch["enabled"])
    if patch.get("merchant_id") is not None:
        merged["merchant_id"] = str(patch["merchant_id"] or "").strip()
    if "sandbox" in patch:
        merged["sandbox"] = bool(patch["sandbox"])
    if patch.get("amount_toman") is not None:
        try:
            merged["amount_toman"] = max(0, int(patch["amount_toman"]))
        except (TypeError, ValueError):
            pass
    if patch.get("subscription_days") is not None:
        try:
            merged["subscription_days"] = max(1, int(patch["subscription_days"]))
        except (TypeError, ValueError):
            pass
    if patch.get("callback_url") is not None:
        merged["callback_url"] = str(patch["callback_url"] or "").strip()
    if patch.get("description") is not None:
        merged["description"] = str(patch["description"] or "").strip() or DEFAULT_DESCRIPTION
    if "partner_sms_enabled" in patch:
        merged["partner_sms_enabled"] = bool(patch["partner_sms_enabled"])
    for key in (
        "sms_activation_message",
        "sms_renewal_message",
        "sms_expiry_reminder_message",
        "sms_expired_message",
    ):
        if patch.get(key) is not None:
            merged[key] = str(patch[key] or "").strip()
    current["zarinpal"] = merged
    path = ensure_file("SETTINGS_FILE", "settings.json", {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return merged


def effective_merchant_id(cfg: dict[str, Any] | None = None) -> str:
    """مرچنت واقعی برای API — در sandbox بدون تنظیم، UUID تست."""
    settings = cfg if isinstance(cfg, dict) else get_zarinpal_settings()
    mid = str(settings.get("merchant_id") or "").strip()
    if mid:
        return mid
    if bool(settings.get("sandbox")):
        return SANDBOX_DEFAULT_MERCHANT_ID
    return ""


def plus_amount_toman(settings_root: dict[str, Any] | None = None) -> int:
    """مبلغ پلاس — اول zarinpal.amount_toman سپس vinor_plus_price_toman."""
    zp = get_zarinpal_settings()
    try:
        amt = int(zp.get("amount_toman") or 0)
        if amt > 0:
            return amt
    except (TypeError, ValueError):
        pass
    root = settings_root if isinstance(settings_root, dict) else {}
    try:
        raw = root.get("vinor_plus_price_toman")
        if raw is not None and str(raw).strip() != "":
            return max(0, int(raw))
    except (TypeError, ValueError):
        pass
    return 990_000


def plus_subscription_days() -> int:
    """تعداد روز اشتراک پس از هر پرداخت/تمدید موفق."""
    zp = get_zarinpal_settings()
    try:
        days = int(zp.get("subscription_days") or 0)
        if days > 0:
            return days
    except (TypeError, ValueError):
        pass
    return DEFAULT_SUBSCRIPTION_DAYS


def payment_flow_active() -> bool:
    """درگاه برای CTA فعال است؟"""
    if not plus_system_enabled():
        return False
    cfg = get_zarinpal_settings()
    return bool(effective_merchant_id(cfg))
