from __future__ import annotations

import threading
from typing import Any

from app.business_intelligence.config import bi_enabled, load_bi_config
from app.business_intelligence.di import make_business_intelligence_manager
from app.business_intelligence.interfaces import (
    BusinessInsights,
    BusinessIntelligenceManager,
    BusinessIntelligenceRequest,
)

_LOCK = threading.Lock()
_MANAGER: BusinessIntelligenceManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_BI: dict[str, Any] = {}


def get_bi_manager() -> BusinessIntelligenceManager | None:
    global _MANAGER
    if not bi_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_business_intelligence_manager()
    return _MANAGER


def _store_obs(insights: BusinessInsights | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_BI
    if insights is None:
        obs: dict[str, Any] = {}
        data: dict[str, Any] = {}
        _FALLBACK_OBS = {}
        _FALLBACK_BI = {}
    else:
        data = insights.to_dict()
        _FALLBACK_BI = data
        metrics = insights.business_metrics or {}
        obs = {
            "market_score": float(metrics.get("market_score") or 0),
            "property_score": float(metrics.get("property_score") or 0),
            "lead_score": float(metrics.get("lead_score") or 0),
            "trend_score": float(metrics.get("trend_score") or 0),
            "opportunity_score": float(insights.opportunity_score or 0),
            "analysis_time_ms": int(insights.analysis_time_ms or 0),
            "risk_count": len(insights.risk_indicators or []),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_business_intelligence_obs = dict(obs)
            g.ai_business_intelligence = data
    except Exception:
        pass


def _merge_os_kpis(obs: dict[str, Any]) -> dict[str, Any]:
    """Phase 7 — inject North Star OS KPIs as os_* keys (fail-open)."""
    out = dict(obs or {})
    try:
        from app.hardening.config import hardening_os_kpis_enabled
        from app.hardening.os_kpis import compute_os_kpis

        if not hardening_os_kpis_enabled():
            return out
        kpis = compute_os_kpis()
        for key, val in (kpis or {}).items():
            out[f"os_{key}"] = val
    except Exception:
        pass
    return out


def get_bi_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_business_intelligence_obs", None)
            if isinstance(raw, dict):
                return _merge_os_kpis(raw)
    except Exception:
        pass
    base = dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "market_score": 0.0,
        "property_score": 0.0,
        "lead_score": 0.0,
        "trend_score": 0.0,
        "opportunity_score": 0.0,
        "analysis_time_ms": 0,
        "risk_count": 0,
    }
    return _merge_os_kpis(base)


def get_business_intelligence() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_business_intelligence", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_BI) if _FALLBACK_BI else {}


def clear_business_intelligence() -> None:
    _store_obs(None)


def _soft_property_metadata(code: str) -> dict[str, Any]:
    """Read-only lookup of existing land metadata — not a search/RAG."""
    if not code:
        return {}
    try:
        from app.utils.storage import load_ads

        ads = load_ads() or []
        for ad in ads:
            if not isinstance(ad, dict):
                continue
            c = str(ad.get("code") or ad.get("id") or "").strip()
            if c == code:
                # shallow copy of safe fields only
                out = {
                    "code": c,
                    "status": ad.get("status") or ad.get("state") or "",
                    "price": ad.get("price") or ad.get("price_toman") or ad.get("amount"),
                    "city": ad.get("city") or ad.get("region") or "",
                }
                if ad.get("updated_at") or ad.get("created_at"):
                    out["age_days"] = None  # unknown without parsing; analyzer uses default
                return out
    except Exception:
        pass
    return {}


def run_business_intelligence(
    *,
    message: str = "",
    route: str = "",
    shared: dict[str, Any] | None = None,
) -> BusinessInsights | None:
    """Fail-open — writes g.ai_business_intelligence + shared key; no prompt injection."""
    manager = get_bi_manager()
    if manager is None:
        return None
    try:
        shared = dict(shared or {})
        decision: dict[str, Any] = {}
        evaluation: dict[str, Any] = {}
        try:
            from flask import g, has_app_context, has_request_context

            if has_app_context() or has_request_context():
                if not shared.get("customer_profile"):
                    shared["customer_profile"] = getattr(g, "ai_customer_profile", None) or {}
                if not shared.get("negotiation_plan"):
                    shared["negotiation_plan"] = getattr(g, "ai_negotiation_plan", None) or {}
                if not shared.get("customer_success"):
                    shared["customer_success"] = getattr(g, "ai_customer_success", None) or {}
                decision = getattr(g, "ai_decision", None) or {}
                evaluation = getattr(g, "ai_evaluation", None) or {}
        except Exception:
            pass
        if not decision:
            try:
                from app.decision.service import get_decision

                decision = get_decision() or {}
            except Exception:
                decision = {}

        code = str(
            (decision or {}).get("selected_property")
            or shared.get("recommended_code")
            or ""
        )
        meta = _soft_property_metadata(code)
        insights = manager.analyze(
            BusinessIntelligenceRequest(
                message=message or "",
                route=route or "",
                shared=shared,
                decision=dict(decision or {}),
                evaluation=dict(evaluation or {}),
                property_metadata=meta,
                config=load_bi_config(),
            )
        )
        _store_obs(insights)
        try:
            shared["business_intelligence"] = insights.to_dict()
        except Exception:
            pass
        return insights
    except Exception:
        return None
