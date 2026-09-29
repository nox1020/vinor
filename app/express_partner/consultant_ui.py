# -*- coding: utf-8 -*-
"""صفحات وب آنبوردینگ بازاریاب — همان API نقش consultant.

ورود: خانه → /express/partner/consultant
اگر درخواست ثبت شده باشد وضعیت، وگرنه شروع.
فرم‌ها خودشان /api/consultant/* را صدا می‌زنند.
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


def _continue_target(step: str) -> tuple[str, str]:
    if step == "profile":
        return url_for("express_partner.consultant_profile"), "تکمیل پروفایل"
    if step == "documents":
        return url_for("express_partner.consultant_documents"), "بارگذاری مدارک"
    if step == "dashboard":
        return url_for("express_partner.home"), "ورود به خانه"
    return "", ""


@express_partner_bp.get("/consultant", endpoint="consultant_gate")
def consultant_gate():
    """خانه: درخواست موجود → وضعیت؛ وگرنه شروع."""
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    snap = onboarding_snapshot(phone)
    if snap is None:
        return redirect(url_for("express_partner.consultant_apply"))
    return redirect(url_for("express_partner.consultant_status"))


@express_partner_bp.get("/consultant/apply", endpoint="consultant_apply")
def consultant_apply_page():
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    if onboarding_snapshot(phone) is not None:
        return redirect(url_for("express_partner.consultant_status"))
    return render_template(
        "express_partner/consultant_apply.html",
        step_title=_STEP_TITLES["apply"],
    )


@express_partner_bp.get("/consultant/profile", endpoint="consultant_profile")
def consultant_profile_page():
    phone, bounce = _gate()
    if bounce is not None:
        return bounce
    snap = onboarding_snapshot(phone)
    if snap is None:
        return redirect(url_for("express_partner.consultant_apply"))
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
    snap = onboarding_snapshot(phone)
    if snap is None:
        return redirect(url_for("express_partner.consultant_apply"))
    if not snap.get("profile_complete"):
        return redirect(url_for("express_partner.consultant_profile"))
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
    snap = onboarding_snapshot(phone)
    if snap is None:
        return redirect(url_for("express_partner.consultant_apply"))
    continue_url, continue_label = _continue_target(str(snap.get("next_step") or ""))
    return render_template(
        "express_partner/consultant_status.html",
        step_title=_STEP_TITLES["status"],
        seed=snap,
        continue_url=continue_url,
        continue_label=continue_label,
    )
