"""تشخیص اپ اندروید وینور و مقایسه نسخه APK."""
from __future__ import annotations

import re
from typing import Optional

_VINOR_APP_UA = re.compile(
    r'VinorApp/(?:Android|WebViewOnly)(?:/([0-9]+(?:\.[0-9]+)*))?',
    re.IGNORECASE,
)


def is_vinor_apk_request(req) -> bool:
    if (req.headers.get('X-Vinor-App-Version') or '').strip():
        return True
    ua = (req.headers.get('User-Agent') or '')
    return bool(re.search(r'VinorApp/(?:Android|WebViewOnly)', ua, re.IGNORECASE))


def parse_vinor_app_version(user_agent: str = '', header_version: str = '') -> str:
    hv = (header_version or '').strip()
    if hv:
        return hv
    m = _VINOR_APP_UA.search(user_agent or '')
    return (m.group(1) or '').strip() if m else ''


def _version_parts(version: str) -> list[int]:
    parts: list[int] = []
    for piece in str(version or '').strip().split('.'):
        piece = piece.strip()
        if not piece:
            continue
        digits = ''.join(ch for ch in piece if ch.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            parts.append(0)
    return parts


def compare_versions(left: str, right: str) -> int:
    """-1 اگر left<right، 0 برابر، 1 اگر left>right."""
    a = _version_parts(left)
    b = _version_parts(right)
    n = max(len(a), len(b))
    a.extend([0] * (n - len(a)))
    b.extend([0] * (n - len(b)))
    for x, y in zip(a, b):
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


def is_server_apk_newer(server_version: str, client_version: str) -> bool:
    server = (server_version or '').strip()
    client = (client_version or '').strip()
    if not server:
        return False
    if not client:
        return False
    return compare_versions(client, server) < 0


def should_show_apk_update(
    server_version: str,
    *,
    client_version: Optional[str] = None,
    apk_url: str = '',
    req=None,
) -> bool:
    hdr_client = ''
    if req is not None:
        hdr_client = (req.headers.get('X-Vinor-App-Version') or '').strip()
    is_apk = bool(hdr_client) or (req is not None and is_vinor_apk_request(req))
    if not is_apk:
        return False
    if not (apk_url or '').strip():
        return False
    if not (server_version or '').strip():
        return False
    if client_version is not None and str(client_version).strip():
        client = str(client_version).strip()
    elif req is not None:
        ua = req.headers.get('User-Agent') or ''
        client = parse_vinor_app_version(ua, hdr_client)
    else:
        client = hdr_client
    return is_server_apk_newer(server_version, client)
