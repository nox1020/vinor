# -*- coding: utf-8 -*-
"""Canonical Iran mobile: 09xxxxxxxxx (ASCII digits)."""
from __future__ import annotations

from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile, normalize_otp_code


def canonical_mobile(phone: str) -> str:
    return normalize_iran_mobile(phone or "")


def is_canonical_mobile(phone: str) -> bool:
    return is_valid_iran_mobile(canonical_mobile(phone))


def canonical_otp_code(code: str, digits: int | None = None) -> str:
    normalized = normalize_otp_code(code)
    if digits is None:
        return normalized
    if len(normalized) != digits:
        return ""
    return normalized
