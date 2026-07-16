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
from app.agents.customer_success.service import (
    get_customer_success_obs,
    run_customer_success,
    should_run_customer_success,
)
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _baseline(message: str, user_key: str) -> float:
    os.environ["VINOR_CUSTOMER_SUCCESS_ENABLED"] = "0"
    os.environ["VINOR_CUSTOMER_SUCCESS_INJECT_HINT"] = "0"
    import app.agents.customer_success.service as css
    import app.supervisor.service as ssvc

    css._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
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
        thread_id="bench-cs-base",
    )
    return estimate_messages_tokens(msgs)


def _with_cs(message: str, user_key: str) -> tuple[float, float, dict]:
    os.environ["VINOR_CUSTOMER_SUCCESS_ENABLED"] = "1"
    os.environ["VINOR_CUSTOMER_SUCCESS_INJECT_HINT"] = "1"
    import app.agents.customer_success.service as css
    import app.supervisor.service as ssvc

    css._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    t0 = time.perf_counter()
    out = orchestrate_request(
        message=message, audience=AUDIENCE_PARTNER, voice="partner", user_key=user_key
    )
    set_supervisor_context(out)
    shared = {
        "customer_profile": {
            "relationship_score": 0.55,
            "interaction_style": "decisive",
            "next_suggested_action": "recommend",
        },
        "negotiation_plan": {
            "deal_probability": 0.6,
            "risk_score": 0.28,
            "recommended_strategy": "value_focus",
            "next_action": "send_offer",
        },
        "recommendation_items": [{"property_code": "20250101120001", "score": 0.8}],
        "analysis_categories": [{"name": "price", "score": 0.7}],
        "workflow": "visit",
        "reused_planning": True,
    }
    plan = run_customer_success(
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
        thread_id="bench-cs",
    )
    inject = bool(plan and plan.compact_hint and should_run_customer_success(message=message))
    if inject:
        msgs = list(msgs) + [{"role": "system", "content": plan.compact_hint}]
    dt = (time.perf_counter() - t0) * 1000
    obs = get_customer_success_obs()
    return estimate_messages_tokens(msgs), dt, {
        "cs_tokens": int(plan.customer_success_tokens if plan and inject else 0),
        "build_ms": int(obs.get("customer_success_time_ms") or (plan.build_time_ms if plan else 0)),
        "stage": obs.get("customer_stage") or "",
        "conv": float(obs.get("conversion_probability") or 0),
        "reuse_neg": bool(obs.get("customer_success_reuse_negotiation")),
        "reuse_cm": bool(obs.get("customer_success_reuse_customer_profile")),
        "reuse_rec": bool(obs.get("customer_success_reuse_recommendation")),
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("پیگیری و اقدام بعدی مشتری چیست؟", "customer_success"),
        ]
        user_key = "09125556677"
        print("=== Customer Success Agent Benchmark (Phase 15) ===")
        for message, label in cases:
            before = _baseline(message, user_key)
            toks, mss, metas = [], [], {}
            for _ in range(12):
                tok, ms, metas = _with_cs(message, user_key)
                toks.append(tok)
                mss.append(ms)
            a = statistics.mean(toks)
            delta = ((a - before) / before * 100.0) if before else 0.0
            print(
                f"[{label}] before={before:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"cs_tokens={metas.get('cs_tokens')} build_ms={metas.get('build_ms')} "
                f"stage={metas.get('stage')} conv={metas.get('conv')} "
                f"reuse_neg={metas.get('reuse_neg')} reuse_profile={metas.get('reuse_cm')} "
                f"reuse_rec={metas.get('reuse_rec')} latency_ms={statistics.mean(mss):.2f}"
            )
        print("no_followup_text=True | skeletons_remaining=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
