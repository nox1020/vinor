# -*- coding: utf-8 -*-
"""Internal-only redirect targets for login and session flows.

Fully decode the candidate, then accept only a single-slash relative path.
Anything else — a second slash, a backslash, whitespace, a control character,
a scheme, or a host — falls back to the home page.
"""
from __future__ import annotations

from urllib.parse import unquote, urlsplit

HOME_PATH = "/"
_DECODE_ROUNDS = 8


def _fully_unquote(value: str) -> str:
    current = value
    for _ in range(_DECODE_ROUNDS):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _has_whitespace_or_control(value: str) -> bool:
    for ch in value:
        if ch.isspace() or ord(ch) < 32 or ord(ch) == 127:
            return True
    return False


def _decoded_is_internal(value: str) -> bool:
    if not value or _has_whitespace_or_control(value) or "\\" in value:
        return False
    if value.startswith("\\") or value.startswith("//") or value.startswith("/\\"):
        return False
    if not value.startswith("/"):
        return False
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return False
    path = parts.path or ""
    if not path.startswith("/") or path.startswith("//") or path.startswith("/\\") or "\\" in path:
        return False
    return True


def safe_internal_path(raw: str | None) -> str | None:
    """Return the fully decoded internal path, or None when it is missing or unsafe."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    if raw == "":
        return None
    decoded = _fully_unquote(raw)
    if not _decoded_is_internal(decoded):
        return None
    return decoded


def safe_internal_path_or_home(raw: str | None) -> str:
    """Safe internal path, or the home page when the candidate is unusable."""
    if raw is None or (isinstance(raw, str) and raw == ""):
        return HOME_PATH
    return safe_internal_path(raw) or HOME_PATH


def safe_request_target() -> str:
    """Current request path plus query, or home when that target is not internal."""
    from flask import request

    path = request.path or HOME_PATH
    query = ""
    try:
        if request.query_string:
            query = request.query_string.decode("latin-1", "ignore")
    except Exception:
        query = ""
    raw = f"{path}?{query}" if query else path
    return safe_internal_path(raw) or safe_internal_path(path) or HOME_PATH
