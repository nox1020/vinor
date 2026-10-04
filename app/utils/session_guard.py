# -*- coding: utf-8 -*-
"""Send browsers with an invalid or expired session cookie to login.

A rotated SECRET_KEY makes the existing cookie fail its signature check. Flask
would otherwise open an empty session and later surface a raw CSRF error.
"""
from __future__ import annotations

from flask import jsonify, redirect, request, session, url_for
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature

from app.utils.safe_redirect import safe_internal_path, safe_request_target

INVALID_SESSION_ENV = "vinor.invalid_session"

_SKIP_PREFIXES = (
    "/static/",
    "/uploads/",
    "/.well-known/",
    "/api/",
    "/express/partner/api/",
    "/admin/api/",
    "/auth/",
)
_SKIP_EXACT = {
    "/sw.js",
    "/manifest.webmanifest",
    "/favicon.ico",
    "/robots.txt",
    "/sitemap.xml",
    "/git-webhook",
    "/express/partner/login",
    "/express/partner/verify",
    "/express/partner/otp/resend",
    "/admin/login",
}


class VinorSessionInterface(SecureCookieSessionInterface):
    def open_session(self, app, request):
        serializer = self.get_signing_serializer(app)
        if serializer is None:
            return None
        raw = request.cookies.get(self.get_cookie_name(app))
        if not raw:
            return self.session_class()
        max_age = int(app.permanent_session_lifetime.total_seconds())
        try:
            data = serializer.loads(raw, max_age=max_age)
            return self.session_class(data)
        except BadSignature:
            request.environ[INVALID_SESSION_ENV] = "1"
            return self.session_class()


def _wants_json() -> bool:
    path = request.path or ""
    if path.startswith("/api/") or "/api/" in path:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.headers.get("Accept") or ""
    content_type = request.headers.get("Content-Type") or ""
    if "application/json" in content_type:
        return True
    if "application/json" in accept and "text/html" not in accept:
        return True
    return False


def _is_auth_or_asset_path(path: str) -> bool:
    if path in _SKIP_EXACT:
        return True
    if path.startswith(_SKIP_PREFIXES):
        return True
    if path.startswith("/express/partner/login"):
        return True
    if path.endswith("/sw.js") or path.endswith("/manifest.webmanifest"):
        return True
    return False


def invalid_session_response():
    """Login redirect for document navigations; JSON 401 for API clients."""
    if _wants_json():
        resp = jsonify({
            "ok": False,
            "error": "session_expired",
            "message": "برای امنیت بیشتر، دوباره وارد شوید",
        })
        resp.status_code = 401
        return resp
    target = safe_request_target()
    path = request.path or "/"
    if path.startswith("/admin"):
        return redirect(url_for("admin.login", next=target))
    preserved = safe_internal_path(request.values.get("next")) if path.startswith("/express/partner/login") else None
    return redirect(url_for("express_partner.login", next=preserved or target, reauth=1))


def install_session_guard(app) -> None:
    app.session_interface = VinorSessionInterface()

    @app.before_request
    def _redirect_invalid_web_session():
        if request.environ.get(INVALID_SESSION_ENV) != "1":
            return None
        try:
            session.modified = True
        except Exception:
            pass
        path = request.path or "/"
        if _is_auth_or_asset_path(path):
            return None
        if request.method not in ("GET", "HEAD", "POST"):
            return None
        return invalid_session_response()
