# -*- coding: utf-8 -*-
"""Legacy Vinor Control hub URLs — kept as redirects to the dashboard.

Sidebar badges now come from admin/nav.py (inject_admin_nav).
"""
from __future__ import annotations

from flask import redirect, url_for

from .blueprint import admin_bp
from .routes import login_required


def _legacy_control_redirect():
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/control/market", endpoint="control_market")
@admin_bp.route("/control/crm", endpoint="control_crm")
@admin_bp.route("/control/people", endpoint="control_people")
@admin_bp.route("/control/analytics", endpoint="control_analytics")
@admin_bp.route("/control/observe", endpoint="control_observe")
@admin_bp.route("/control/reasoning", endpoint="control_reasoning")
@admin_bp.route("/control/evaluations", endpoint="control_evaluations")
@admin_bp.route("/control/more", endpoint="control_more")
@login_required
def control_legacy_hubs():
    """Mission Control hubs removed — redirect to ops chat home."""
    return _legacy_control_redirect()
