from __future__ import annotations

import json
import os
import time
from collections import Counter
from typing import Any

from app.business_ai.interfaces import AutonomousBusinessAI, BusinessReport


def business_ai_enabled() -> bool:
    return (os.environ.get("VINOR_BUSINESS_AI_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _dir() -> str:
    try:
        from flask import current_app

        root = current_app.instance_path
    except Exception:
        root = os.path.join(os.getcwd(), "instance")
    path = os.path.join(root, "data", "business_ai")
    os.makedirs(path, exist_ok=True)
    return path


class RuleAutonomousBusinessAI(AutonomousBusinessAI):
    """Management reports from existing logs — outside prompt."""

    def analyze(
        self, *, evaluation: list[dict[str, Any]], bi_rows: list[dict[str, Any]]
    ) -> BusinessReport:
        t0 = time.perf_counter()
        evaluation = evaluation or []
        bi_rows = bi_rows or []
        regions = Counter()
        props = Counter()
        partners = Counter()
        conversions = []
        costs = []
        for r in evaluation:
            intent = str(r.get("intent") or r.get("workflow") or "")
            if intent:
                regions[intent] += 1
            sel = str(r.get("property_selected") or r.get("decision_selected_property") or "")
            if sel:
                props[sel] += 1
            role = str(r.get("role") or r.get("audience") or "")
            if role:
                partners[role] += 1
            q = r.get("quality") if isinstance(r.get("quality"), dict) else {}
            conversions.append(float(q.get("overall") or r.get("decision_confidence") or 0))
            costs.append(float(r.get("estimated_cost") or r.get("total_cost") or 0))
        for b in bi_rows:
            if b.get("market_score"):
                regions["bi_market"] += 1

        report = BusinessReport(
            best_regions=[{"region_or_intent": k, "count": c} for k, c in regions.most_common(5)],
            high_sale_probability=[{"property": k, "hits": c} for k, c in props.most_common(5)],
            high_conversion_customers=[
                {"signal": "high_quality", "avg": round(sum(conversions) / len(conversions), 3)}
            ]
            if conversions
            else [],
            partner_performance=[{"audience": k, "count": c} for k, c in partners.most_common(5)],
            market_opportunities=[
                "تمرکز روی intentهای پرتکرار",
                "پیگیری فایل‌های با hit بالا",
            ],
            sales_trends={
                "sample_count": len(evaluation),
                "avg_quality": round(sum(conversions) / len(conversions), 3) if conversions else 0,
            },
            revenue_insights={
                "avg_cost": round(sum(costs) / len(costs), 8) if costs else 0,
                "note": "proxy از AI cost نه درآمد واقعی",
            },
            growth_suggestions=[
                "تقویت مسیر Search→Decision برای فایل‌های پرتقاضا",
                "بازبینی همکاران با performance پایین",
            ],
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
        try:
            path = os.path.join(_dir(), f"report_{int(time.time())}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            with open(os.path.join(_dir(), "latest.json"), "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return report
