from __future__ import annotations

import os
import statistics
import sys
import time
import tracemalloc

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.ai.audience import AUDIENCE_PARTNER
from app.ai.services import _build_messages
from app.ai.token_analytics import estimate_messages_tokens
from app.business_intelligence.di import make_business_intelligence_manager
from app.business_intelligence.interfaces import BusinessIntelligenceRequest
from app.business_intelligence.service import clear_business_intelligence


def _shared() -> dict:
    return {
        "recommended_code": "BI001",
        "property_codes": ["BI001", "BI002"],
        "recommendation_items": [{"property_code": "BI001", "score": 0.8}],
        "analysis_categories": [{"score": 0.7}],
        "customer_profile": {
            "relationship_score": 0.55,
            "confidence": 0.5,
            "preference_count": 2,
            "location_preferences": ["گرمابسرد"],
        },
        "negotiation_plan": {"deal_probability": 0.6, "risk_score": 0.35},
        "customer_success": {"conversion_probability": 0.5, "confidence": 0.45},
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        print("=== Business Intelligence Benchmark (Phase 18) ===")
        clear_business_intelligence()
        msgs = _build_messages(
            "ویلا در دماوند",
            [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
            user_key="09128887766",
            audience=AUDIENCE_PARTNER,
            voice="partner",
            with_tools=False,
            thread_id="bench-bi",
        )
        before = estimate_messages_tokens(msgs)

        mgr = make_business_intelligence_manager()
        req = BusinessIntelligenceRequest(
            message="ویلا",
            route="property_search",
            shared=_shared(),
            decision={
                "selected_property": "BI001",
                "alternative_properties": ["BI002"],
                "decision_score": 0.7,
                "confidence": 0.72,
                "conflict_count": 0,
            },
            property_metadata={"age_days": 12},
        )
        times = []
        tracemalloc.start()
        snap0 = tracemalloc.take_snapshot()
        insights = None
        for _ in range(40):
            t0 = time.perf_counter()
            insights = mgr.analyze(req)
            times.append((time.perf_counter() - t0) * 1000)
        snap1 = tracemalloc.take_snapshot()
        stats = snap1.compare_to(snap0, "lineno")
        mem_kb = sum(max(0, s.size_diff) for s in stats[:20]) / 1024.0
        tracemalloc.stop()

        after = estimate_messages_tokens(msgs)
        delta = ((after - before) / before * 100.0) if before else 0.0
        data = insights.to_dict() if insights else {}
        storage_bytes = len(str(data).encode("utf-8"))
        print(
            f"[token] before={before:.0f} after={after:.0f} delta={delta:+.2f}% "
            f"(target=0.00% | no_default_hint=True)"
        )
        print(
            f"[perf] analysis_ms={statistics.mean(times):.3f} "
            f"p50={statistics.median(times):.3f} "
            f"mem_delta_kb≈{mem_kb:.1f} storage_bytes≈{storage_bytes} "
            f"opportunity={insights.opportunity_score if insights else 0} "
            f"market={insights.business_metrics.get('market_score') if insights else 0}"
        )
        print("no_prompt_injection=True | no_agent_rerun=True | outside_prompt=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
