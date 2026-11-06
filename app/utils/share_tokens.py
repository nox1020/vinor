"""Partner referral tokens.

New tokens are Fernet ciphertext derived from SECRET_KEY, so the phone is not
recoverable by base64-decoding the link. Links issued before this change are
still accepted when they decode to an Iranian mobile.
"""
from __future__ import annotations

import base64
import hashlib
import os

_LEGACY_PREFIX = ""  # historical tokens are raw urlsafe base64 of the phone


def _normalize_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if not phone:
        return ""
    try:
        from app.services.notifications import _normalize_user_id

        return _normalize_user_id(phone) or phone
    except Exception:
        return phone


def _looks_like_mobile(value: str) -> bool:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return len(digits) == 11 and digits.startswith("09")


def _fernet():
    secret = (os.environ.get("SECRET_KEY") or "").strip().encode()
    if not secret:
        return None
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    key = base64.urlsafe_b64encode(
        hashlib.sha256(b"vinor-partner-ref-v1\0" + secret).digest()
    )
    return Fernet(key)


def encode_partner_ref(phone: str) -> str:
    """Return an opaque token for a partner phone. Empty when phone or key is missing."""
    phone = _normalize_phone(phone)
    if not _looks_like_mobile(phone):
        return ""
    box = _fernet()
    if box is None:
        return ""
    return box.encrypt(phone.encode("utf-8")).decode("ascii")


def _decode_legacy(token: str) -> str:
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token + padding).decode("utf-8")
    except Exception:
        return ""
    if not _looks_like_mobile(raw):
        return ""
    return _normalize_phone(raw) or raw


def decode_partner_ref(token: str) -> str:
    """Return the partner phone, or empty when the token is not a known link."""
    token = (token or "").strip()
    if not token:
        return ""
    box = _fernet()
    if box is not None:
        try:
            phone = box.decrypt(token.encode("ascii"), ttl=None).decode("utf-8")
        except Exception:
            phone = ""
        if _looks_like_mobile(phone):
            return _normalize_phone(phone) or phone
    return _decode_legacy(token)
