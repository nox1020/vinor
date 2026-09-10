"""تشخیص اپ اندروید وینور و مقایسه نسخه APK."""
from __future__ import annotations

import re
from typing import Optional

_VINOR_APP_UA = re.compile(
    r'VinorApp/(?:Android|WebViewOnly|Native)(?:/([0-9]+(?:\.[0-9]+)*))?',
    re.IGNORECASE,
)


def is_vinor_apk_request(req) -> bool:
    if (req.headers.get('X-Vinor-App-Version') or '').strip():
        return True
    if (req.headers.get('X-Vinor-App-Version-Code') or '').strip():
        return True
    ua = (req.headers.get('User-Agent') or '')
    return bool(re.search(r'VinorApp/(?:Android|WebViewOnly|Native)', ua, re.IGNORECASE))


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


def parse_vinor_app_version_code(req=None, header_code: str = '') -> int:
    raw = (header_code or '').strip()
    if not raw and req is not None:
        raw = (req.headers.get('X-Vinor-App-Version-Code') or '').strip()
    try:
        n = int(str(raw).split('.')[0])
        return n if n > 0 else 0
    except (TypeError, ValueError):
        return 0


def resolve_android_apk_version_code(settings: Optional[dict] = None) -> int:
    """versionCode ذخیره‌شده، در غیر این صورت از فایل APK، در نهایت از versionName."""
    data = settings if isinstance(settings, dict) else {}
    raw = data.get('android_apk_version_code')
    try:
        stored = int(raw)
        if stored > 0:
            return stored
    except (TypeError, ValueError):
        pass
    try:
        from .apk_meta import extract_apk_version_code, version_code_from_name
        from .short_urls import resolve_apk_filesystem_path

        fp, _name = resolve_apk_filesystem_path(data)
        if fp:
            code = int(extract_apk_version_code(fp) or 0)
            if code > 0:
                return code
        return version_code_from_name(str(data.get('android_apk_version') or ''))
    except Exception:
        return 0


def android_apk_version_payload(settings: Optional[dict] = None) -> dict:
    data = settings if isinstance(settings, dict) else {}
    version_name = str(data.get('android_apk_version') or '').strip()
    version_code = resolve_android_apk_version_code(data)
    min_code = 0
    try:
        min_code = int(data.get('android_apk_min_supported_version_code') or 0)
    except (TypeError, ValueError):
        min_code = 0
    return {
        'android_apk_version': version_name,
        'android_apk_version_name': version_name,
        'android_apk_version_code': version_code if version_code > 0 else 0,
        'android_apk_min_supported_version_code': min_code if min_code > 0 else 0,
    }


def should_show_apk_update(
    server_version: str,
    *,
    client_version: Optional[str] = None,
    apk_url: str = '',
    req=None,
    server_version_code: int = 0,
    client_version_code: int = 0,
) -> bool:
    hdr_client = ''
    if req is not None:
        hdr_client = (req.headers.get('X-Vinor-App-Version') or '').strip()
    is_apk = bool(hdr_client) or (req is not None and is_vinor_apk_request(req))
    if not is_apk:
        return False
    if not (apk_url or '').strip():
        return False
    if not (server_version or '').strip() and int(server_version_code or 0) <= 0:
        return False
    client_code = int(client_version_code or 0)
    if client_code <= 0:
        client_code = parse_vinor_app_version_code(req)
    server_code = int(server_version_code or 0)
    if server_code > 0 and client_code > 0:
        return client_code < server_code
    if client_version is not None and str(client_version).strip():
        client = str(client_version).strip()
    elif req is not None:
        ua = req.headers.get('User-Agent') or ''
        client = parse_vinor_app_version(ua, hdr_client)
    else:
        client = hdr_client
    return is_server_apk_newer(server_version, client)
