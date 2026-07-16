from __future__ import annotations

import os
import statistics
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.ai.audience import AUDIENCE_PARTNER
from app.ai.services import _build_messages
from app.ai.token_analytics import estimate_messages_tokens
from app.agents.negotiation.service import (
    get_negotiation_obs,
    run_negotiation,
    should_run_negotiation,
)
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _baseline(message: str, user_key: str) -> tuple[float, float]:
    os.environ["VINOR_NEGOTIATION_ENABLED"] = "0"
    os.environ["VINOR_NEGOTIATION_INJECT_HINT"] = "0"
    import app.agents.negotiation.service as ns
    import app.supervisor.service as ssvc

    ns._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    t0 = time.perf_counter()
    out = orchestrate_request(
        message=message, audience=AUDIENCE_PARTNER, voice="partner", user_key=user_key
    )
    set_supervisor_context(out)
    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-neg-base",
    )
    return estimate_messages_tokens(msgs), (time.perf_counter() - t0) * 1000


def _with_neg(message: str, user_key: str) -> tuple[float, float, dict]:
    os.environ["VINOR_NEGOTIATION_ENABLED"] = "1"
    os.environ["VINOR_NEGOTIATION_INJECT_HINT"] = "1"
    import app.agents.negotiation.service as ns
    import app.supervisor.service as ssvc

    ns._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    t0 = time.perf_counter()
    out = orchestrate_request(
        message=message, audience=AUDIENCE_PARTNER, voice="partner", user_key=user_key
    )
    set_supervisor_context(out)
    shared = {
        "recommended_code": "20250101120001",
        "asking_price": 15_000_000_000,
        "recommendation_items": [{"property_code": "20250101120001", "score": 0.8}],
        "analysis_categories": [{"name": "price", "score": 0.65}],
        "customer_profile": {
            "interaction_style": "decisive",
            "relationship_score": 0.55,
            "preferences": {"budget_max": 14_000_000_000},
            "budget_profile": {"max": 14_000_000_000},
        },
        "reused_planning": True,
    }
    plan = run_negotiation(
        message=message,
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        shared=shared,
        context_budget_chars=55,
    )
    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-neg",
    )
    inject = bool(plan and plan.compact_hint and should_run_negotiation(message=message))
    if inject:
        msgs = list(msgs) + [{"role": "system", "content": plan.compact_hint}]
    dt = (time.perf_counter() - t0) * 1000
    obs = get_negotiation_obs()
    return estimate_messages_tokens(msgs), dt, {
        "neg_tokens": int(plan.negotiation_tokens if plan and inject else 0),
        "build_ms": int(obs.get("negotiation_time_ms") or (plan.negotiation_time_ms if plan else 0)),
        "confidence": float(obs.get("negotiation_confidence") or 0),
        "risk": float(obs.get("negotiation_risk") or 0),
        "deal_p": float(obs.get("deal_probability") or 0),
        "reuse_rec": bool(obs.get("negotiation_reuse_recommendation")),
        "reuse_an": bool(obs.get("negotiation_reuse_analysis")),
        "reuse_cm": bool(obs.get("negotiation_reuse_customer_profile")),
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("برای این فایل مذاکره و تخفیف می‌خوام", "negotiation"),
        ]
        user_key = "09123334455"
        print("=== Negotiation Agent Benchmark (Phase 14) ===")
        for message, label in cases:
            before_tok, _ = _baseline(message, user_key)
            toks, mss, metas = [], [], {}
            for _ in range(12):
                tok, ms, metas = _with_neg(message, user_key)
                toks.append(tok)
                mss.append(ms)
            a = statistics.mean(toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"neg_tokens={metas.get('neg_tokens')} build_ms={metas.get('build_ms')} "
                f"confidence={metas.get('confidence')} risk={metas.get('risk')} "
                f"deal_p={metas.get('deal_p')} reuse_rec={metas.get('reuse_rec')} "
                f"reuse_analysis={metas.get('reuse_an')} reuse_profile={metas.get('reuse_cm')} "
                f"latency_ms={statistics.mean(mss):.2f}"
            )
        print("no_dialogue_text=True | follow_up=skeleton")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
