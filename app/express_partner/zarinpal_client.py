# -*- coding: utf-8 -*-
"""کلاینت REST زرین‌پال v4 — درخواست و تأیید پرداخت (sandbox/production)."""
from __future__ import annotations

from typing import Any, Optional, Tuple

import requests

from .zarinpal_config import effective_merchant_id, get_zarinpal_settings

SANDBOX_API_BASE = "https://sandbox.zarinpal.com/pg/v4/payment"
PRODUCTION_API_BASE = "https://api.zarinpal.com/pg/v4/payment"

SANDBOX_START_BASE = "https://sandbox.zarinpal.com/pg/StartPay"
PRODUCTION_START_BASE = "https://www.zarinpal.com/pg/StartPay"

REQUEST_SUCCESS_CODES = frozenset({100})
VERIFY_SUCCESS_CODES = frozenset({100, 101})


def toman_to_rial(amount_toman: int) -> int:
    return max(0, int(amount_toman)) * 10


def api_bases(*, sandbox: bool) -> Tuple[str, str]:
    if sandbox:
        return SANDBOX_API_BASE, SANDBOX_START_BASE
    return PRODUCTION_API_BASE, PRODUCTION_START_BASE


def is_request_success(code: Any) -> bool:
    try:
        return int(code) in REQUEST_SUCCESS_CODES
    except (TypeError, ValueError):
        return False


def is_verify_success(code: Any) -> bool:
    try:
        return int(code) in VERIFY_SUCCESS_CODES
    except (TypeError, ValueError):
        return False


def amounts_match(expected_toman: int, verify_amount_rial: Any) -> bool:
    """مبلغ برگشتی verify (ریال) با مبلغ ذخیره‌شده (تومان) یکی باشد."""
    if verify_amount_rial is None or str(verify_amount_rial).strip() == "":
        # sandbox / verify تکراری (۱۰۱) گاهی فیلد amount نمی‌فرستد
        return True
    try:
        return int(verify_amount_rial) == toman_to_rial(expected_toman)
    except (TypeError, ValueError):
        return False


def start_pay_url(authority: str, *, sandbox: bool) -> str:
    auth = str(authority or "").strip()
    _, start_base = api_bases(sandbox=sandbox)
    return f"{start_base}/{auth}"


def payment_request(
    *,
    amount_toman: int,
    callback_url: str,
    description: str,
    metadata: Optional[dict[str, Any]] = None,
    merchant_id: Optional[str] = None,
    sandbox: Optional[bool] = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    cfg = get_zarinpal_settings()
    mid = (merchant_id or effective_merchant_id(cfg) or "").strip()
    sb = cfg.get("sandbox") if sandbox is None else bool(sandbox)
    api_base, _ = api_bases(sandbox=sb)
    url = f"{api_base}/request.json"
    payload: dict[str, Any] = {
        "merchant_id": mid,
        "amount": toman_to_rial(amount_toman),
        "callback_url": callback_url,
        "description": (description or "").strip() or "Vinor Plus",
    }
    if metadata:
        payload["metadata"] = metadata
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        body = resp.json() if resp.content else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "authority": None, "raw": None}
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        errors = body.get("errors") if isinstance(body, dict) else body
        return {"ok": False, "error": "invalid_response", "authority": None, "raw": body, "errors": errors}
    code = data.get("code")
    authority = str(data.get("authority") or "").strip() or None
    ok = is_request_success(code) and bool(authority)
    return {
        "ok": ok,
        "code": code,
        "message": data.get("message"),
        "authority": authority,
        "raw": body,
        "error": None if ok else str(data.get("message") or "request_failed"),
    }


def payment_verify(
    *,
    authority: str,
    amount_toman: int,
    merchant_id: Optional[str] = None,
    sandbox: Optional[bool] = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    cfg = get_zarinpal_settings()
    mid = (merchant_id or effective_merchant_id(cfg) or "").strip()
    sb = cfg.get("sandbox") if sandbox is None else bool(sandbox)
    api_base, _ = api_bases(sandbox=sb)
    url = f"{api_base}/verify.json"
    payload = {
        "merchant_id": mid,
        "amount": toman_to_rial(amount_toman),
        "authority": str(authority or "").strip(),
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        body = resp.json() if resp.content else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "ref_id": None, "code": None, "raw": None}
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        errors = body.get("errors") if isinstance(body, dict) else body
        return {"ok": False, "error": "invalid_response", "ref_id": None, "code": None, "raw": body, "errors": errors}
    code = data.get("code")
    ref_id = data.get("ref_id")
    ok = is_verify_success(code) and amounts_match(amount_toman, data.get("amount"))
    if is_verify_success(code) and not amounts_match(amount_toman, data.get("amount")):
        ok = False
        err = "amount_mismatch"
    else:
        err = None if ok else str(data.get("message") or "verify_failed")
    return {
        "ok": ok,
        "code": code,
        "message": data.get("message"),
        "ref_id": ref_id,
        "card_pan": data.get("card_pan"),
        "raw": body,
        "error": err,
    }
