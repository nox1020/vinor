# -*- coding: utf-8 -*-
"""Cryptographically secure OTP generation and HMAC hashing."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from .config import hmac_secret_bytes


def generate_otp(digits: int = 5) -> str:
    if digits < 4 or digits > 8:
        digits = 5
    span = 10 ** digits
    return f"{secrets.randbelow(span):0{digits}d}"


def hash_otp(phone: str, purpose: str, code: str) -> str:
    msg = f"{phone}|{purpose}|{code}".encode("utf-8")
    return hmac.new(hmac_secret_bytes(), msg, hashlib.sha256).hexdigest()


def verify_otp_hash(phone: str, purpose: str, code: str, stored_hash: str) -> bool:
    if not stored_hash:
        dummy = hash_otp(phone or "0", purpose or "x", "000000")
        hmac.compare_digest(dummy, dummy)
        return False
    candidate = hash_otp(phone, purpose, code)
    return hmac.compare_digest(candidate, str(stored_hash))


def hash_identifier(value: str) -> str:
    raw = (value or "").encode("utf-8")
    return hmac.new(hmac_secret_bytes(), raw, hashlib.sha256).hexdigest()


def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) < 6:
        return "****"
    return f"{digits[:4]}****{digits[-2:]}"
