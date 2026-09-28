# -*- coding: utf-8 -*-
"""JSON stub برای آنبوردینگ مشاور فاز ۱.

قرارداد: docs/consultant-onboarding-api.md
نقش API ``consultant`` = برچسب UI «بازاریاب وینور» روی همان مدل Express Partner.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request, session

from app.express_partner.consultant_onboarding import (
    SERVER_MESSAGE,
    apply_simulation,
    cities_payload,
    consultant_api_enabled,
    dry_run_enabled,
    read_status,
    save_documents,
    set_availability,
    start_application,
    update_profile,
)
from app.express_partner.partner_session_sync import canonical_partner_phone

consultant_api_bp = Blueprint("consultant_api", __name__, url_prefix="/api/consultant")

_MAX_BODY = 11 * 1024 * 1024


def _json_err(code: str, message: str, status: int, fields: Optional[dict] = None):
    body: dict = {"ok": False, "error": code, "message": message}
    if fields:
        body["fields"] = fields
    resp = jsonify(body)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status


def _respond(result: Tuple[dict, int]):
    body, status = result
    resp = jsonify(body)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status


def _guard(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            current_app.logger.exception("consultant api failed")
            return _json_err("server", SERVER_MESSAGE, 500)

    return wrapper


def _admin_session() -> bool:
    """نشست ادمین بعد از OTP ادمین: logged_in به‌همراه admin_phone.

    نشست همکار فقط user_phone دارد و این شرط را برقرار نمی‌کند.
    """
    return bool(session.get("logged_in") and session.get("admin_phone"))


def _simulation_allowed() -> bool:
    """نوشتن وضعیت بررسی فقط در dry-run صریح یا نشست ادمین."""
    return dry_run_enabled() or _admin_session()


def _session_phone() -> Tuple[str, Any]:
    raw = session.get("user_phone")
    if not raw:
        return "", _json_err(
            "unauthorized",
            "برای ادامه باید با حساب همکار وارد شوید.",
            401,
        )
    phone = canonical_partner_phone(str(raw))
    if not phone:
        return "", _json_err(
            "unauthorized",
            "برای ادامه باید با حساب همکار وارد شوید.",
            401,
        )
    return phone, None


def _target_phone(data: Optional[dict] = None) -> Tuple[str, Any]:
    phone, err = _session_phone()
    if err:
        return "", err
    if isinstance(data, dict) and _admin_session():
        requested = str(data.get("phone") or "").strip()
        if requested:
            targeted = canonical_partner_phone(requested)
            if not targeted:
                return "", _json_err("validation", "شمارهٔ هدف معتبر نیست.", 400)
            return targeted, None
    return phone, None


@consultant_api_bp.before_request
def _consultant_api_gate():
    if not consultant_api_enabled():
        return _json_err("not_found", "این سرویس در دسترس نیست.", 404)
    return None


@consultant_api_bp.after_request
def _consultant_no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _read_file(field: str) -> Tuple[bool, bytes]:
    storage = request.files.get(field) if request.files else None
    if storage is None or not (storage.filename or "").strip():
        return False, b""
    raw = storage.read(5 * 1024 * 1024 + 1)
    if not isinstance(raw, bytes):
        raw = bytes(raw or b"")
    return True, raw


@consultant_api_bp.post("/apply")
@_guard
def consultant_apply():
    phone, err = _session_phone()
    if err:
        return err
    raw = request.get_data(cache=True) or b""
    if raw.strip() not in (b"", b"{}"):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _json_err("validation", "بدنه باید خالی یا {} باشد.", 400)
    return _respond(start_application(phone))


@consultant_api_bp.patch("/profile")
@_guard
def consultant_profile():
    phone, err = _session_phone()
    if err:
        return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_err("validation", "بدنهٔ درخواست نامعتبر است.", 400)
    return _respond(update_profile(phone, data))


@consultant_api_bp.post("/documents")
@_guard
def consultant_documents():
    phone, err = _session_phone()
    if err:
        return err
    if request.content_length and request.content_length > _MAX_BODY:
        return _json_err(
            "validation",
            "حجم هر فایل حداکثر ۵ مگابایت است.",
            400,
            {"national_id": "حجم هر فایل حداکثر ۵ مگابایت است."},
        )
    national_present, national_raw = _read_file("national_id")
    license_present, license_raw = _read_file("license")
    return _respond(
        save_documents(
            phone,
            national_id=national_raw,
            national_id_present=national_present,
            license_file=license_raw,
            license_present=license_present,
        )
    )


@consultant_api_bp.get("/status")
@_guard
def consultant_status():
    phone, err = _target_phone()
    if err:
        return err
    simulate = (request.args.get("simulate") or request.headers.get("X-Vinor-Consultant-Simulate") or "").strip().lower()
    if simulate:
        if not _simulation_allowed():
            simulate = ""
        elif simulate not in ("approved", "rejected", "pending"):
            return _json_err(
                "validation",
                "وضعیت آزمایشی باید approved، rejected یا pending باشد.",
                400,
                {"simulate": "وضعیت آزمایشی باید approved، rejected یا pending باشد."},
            )
        else:
            reason = request.args.get("reject_reason")
            return _respond(apply_simulation(phone, simulate, reason))
    return _respond(read_status(phone))


@consultant_api_bp.post("/availability")
@_guard
def consultant_availability():
    phone, err = _session_phone()
    if err:
        return err
    data = request.get_json(silent=True)
    return _respond(set_availability(phone, data))


@consultant_api_bp.get("/cities")
@_guard
def consultant_cities():
    _phone, err = _session_phone()
    if err:
        return err
    return _respond((cities_payload(), 200))


@consultant_api_bp.post("/simulate")
@_guard
def consultant_simulate():
    """Dry-run: وضعیت بررسی را روی همین رکورد Partner می‌نویسد.

    وقتی VINOR_CONSULTANT_DRY_RUN خاموش است فقط نشست ادمین مجاز است.
    """
    if not _simulation_allowed():
        return _json_err("not_found", "شبیه‌سازی وضعیت فقط در حالت آزمایشی فعال است.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    phone, err = _target_phone(data)
    if err:
        return err
    return _respond(apply_simulation(phone, str(data.get("status") or ""), data.get("reject_reason")))
