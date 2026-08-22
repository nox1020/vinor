# -*- coding: utf-8 -*-
"""Client metadata for OTP rate limits. Do not trust spoofable forwarding headers."""
from __future__ import annotations

from flask import has_request_context, request


def client_ip() -> str:
    """Use Flask/Werkzeug remote_addr (ProxyFix already applied when TRUST_PROXY=1).

    Reading X-Forwarded-For or X-Real-IP here would let a client rotate IPs
    and bypass the per-IP OTP rate limit.
    """
    if not has_request_context():
        return "unknown"
    return (request.remote_addr or "").strip() or "unknown"


def client_user_agent() -> str:
    if not has_request_context():
        return ""
    return (request.headers.get("User-Agent") or "")[:300]
