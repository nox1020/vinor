# -*- coding: utf-8 -*-
"""Client metadata for OTP rate limits."""
from __future__ import annotations

import ipaddress

from flask import has_request_context, request


def ip_is_public(value: str) -> bool:
    """True for a globally routable address. Loopback and LAN are not one user."""
    text = (value or "").strip()
    if not text or text.lower() == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def public_client_ip(direct: str, forwarded: str = "", real_ip: str = "") -> str:
    """Prefer the socket address. Read forwarding headers only behind a private hop.

    An internet client cannot spoof the limit by sending X-Forwarded-For, because
    that header is ignored when the TCP peer is already a public address. On
    cPanel/Passenger the peer is often 127.0.0.1 and the real client is the
    rightmost public address the proxy appended.
    """
    peer = (direct or "").strip()
    if ip_is_public(peer):
        return peer
    parts = [part.strip() for part in (forwarded or "").split(",") if part.strip()]
    for candidate in reversed(parts):
        if ip_is_public(candidate):
            return candidate
    if ip_is_public(real_ip):
        return real_ip.strip()
    return peer or "unknown"


def client_ip() -> str:
    if not has_request_context():
        return "unknown"
    return public_client_ip(
        request.remote_addr or "",
        request.headers.get("X-Forwarded-For") or "",
        request.headers.get("X-Real-IP") or "",
    )


def client_user_agent() -> str:
    if not has_request_context():
        return ""
    return (request.headers.get("User-Agent") or "")[:300]
