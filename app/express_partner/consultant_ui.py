# -*- coding: utf-8 -*-
"""صفحات وب آنبوردینگ بازاریاب — همان API نقش consultant.

ورود از خانه به /express/partner/consultant و از آنجا با next_step:
S1 شروع، S2 پروفایل، S3 مدارک، S4 وضعیت (انتظار یا رد)، S5 فقط بعد از تأیید.
رد شدن روی S4 می‌ماند. کلید آنلاین فقط روی S5 و فقط وقتی status=approved است.
"""
from __future__ import annotations

from flask import redirect, render_template, request, session, url_for

from app.express_partner.consultant_onboarding import (
    consultant_api_enabled,
    onboarding_snapshot,
)
from app.express_partner.partner_session_sync import canonical_partner_phone

from . import express_partner_bp

_STEP_TITLES = {
    "apply": "شروع درخواست",
    "profile": "پروفایل",
    "documents": "مدارک",
    "status": "وضعیت درخواست",
    "dashboard": "داشبورد",
}


def _phone_or_login():
    raw = session.get("user_phone")
    if not raw:
        return "", redirect(url_for("express_partner.home", menu=1, login_next=request.path))
    phone = canonical_partner_phone(str(raw))
    if not phone:
        return "", redirect(url_for("express_partner.home", menu=1, login_next=request.path))
    return phone, None


def _gate():
    if not consultant_api_enabled():
        return None, redirect(url_for("express_partner.home"))
    phone, bounce = _phone_or_login()
    if bounce is not None:
        return None, bounce
    return phone, None


def _destination(snap) -> str:
    """صفحهٔ بعدی از next_step. داشبورد فقط با تأیید واقعی."""
    if snap is None:
        return "express_partner.consultant_apply"
    step = str(snap.get("next_step") or "")
    status = str(snap.get("status") or "")
    if step == "profile":
        return "express_partner.consultant_profile"
    if step == "documents":
        return "express_partner.consultant_documents"
    if step == "dashboard" and status == "approved":
        return "express_partner.consultant_dashboard"
    return "express_partner.consultant_status"


def _stay(phone: str, endpoint: str):
    snap = onboarding_snapshot(phone)
    dest = _destination(snap)
    if dest != endpoint:
        return snap, redirect(url_for(dest))
    return snap, None


@express_partner_bp.get("/consultant", endpoint="consultant_gate")
def consultant_gate():
    """خانه را با next_step به S1–S5 می‌فرستد. رد شدن S5 نیست."""
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    return redirect(url_for(_destination(onboarding_snapshot(phone))))


@express_partner_bp.get("/consultant/apply", endpoint="consultant_apply")
def consultant_apply_page():
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    _snap, bounce = _stay(phone, "express_partner.consultant_apply")
    if bounce is not None:
        return bounce
    return render_template(
        "express_partner/consultant_apply.html",
        step_title=_STEP_TITLES["apply"],
    )


@express_partner_bp.get("/consultant/profile", endpoint="consultant_profile")
def consultant_profile_page():
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    snap, bounce = _stay(phone, "express_partner.consultant_profile")
    if bounce is not None:
        return bounce
    return render_template(
        "express_partner/consultant_profile.html",
        step_title=_STEP_TITLES["profile"],
        seed=snap,
    )


@express_partner_bp.get("/consultant/documents", endpoint="consultant_documents")
def consultant_documents_page():
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    snap, bounce = _stay(phone, "express_partner.consultant_documents")
    if bounce is not None:
        return bounce
    return render_template(
        "express_partner/consultant_documents.html",
        step_title=_STEP_TITLES["documents"],
        seed=snap,
    )


@express_partner_bp.get("/consultant/status", endpoint="consultant_status")
def consultant_status_page():
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    snap, bounce = _stay(phone, "express_partner.consultant_status")
    if bounce is not None:
        return bounce
    return render_template(
        "express_partner/consultant_status.html",
        step_title=_STEP_TITLES["status"],
        seed=snap,
    )


@express_partner_bp.get("/consultant/dashboard", endpoint="consultant_dashboard")
def consultant_dashboard_page():
    """S5. اسلایدها محلی‌اند. کلید آنلاین فقط همین‌جا و فقط بعد از تأیید رندر می‌شود."""
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    snap, bounce = _stay(phone, "express_partner.consultant_dashboard")
    if bounce is not None:
        return bounce
    if str(snap.get("status") or "") != "approved":
        return redirect(url_for("express_partner.consultant_status"))
    return render_template(
        "express_partner/consultant_dashboard.html",
        step_title=_STEP_TITLES["dashboard"],
        seed=snap,
    )
