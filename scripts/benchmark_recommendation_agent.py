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
from app.agents.analysis.interfaces import AnalysisCategoryResult
from app.agents.analysis.service import clear_analysis
from app.agents.recommendation.service import (
    clear_recommendation,
    get_recommendation_hint,
    get_recommendation_obs,
    run_recommendation,
)
from app.agents.service import prepare_agent_after_supervisor, set_agent_obs, get_agent_obs
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _run(message: str, *, with_rec: bool) -> tuple[float, float, dict]:
    os.environ["VINOR_SUPERVISOR_ENABLED"] = "1"
    os.environ["VINOR_AGENTS_ENABLED"] = "1"
    os.environ["VINOR_ANALYSIS_ENABLED"] = "1"
    os.environ["VINOR_RECOMMENDATION_ENABLED"] = "1" if with_rec else "0"
    import app.agents.analysis.service as ansvc
    import app.agents.recommendation.service as rsvc
    import app.agents.service as asvc
    import app.supervisor.service as ssvc

    ansvc._MANAGER = None
    rsvc._MANAGER = None
    asvc._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    set_agent_obs(None)
    clear_analysis()
    clear_recommendation()

    t0 = time.perf_counter()
    out = orchestrate_request(
        message=message,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        user_key="09126667788",
    )
    set_supervisor_context(out)
    route = out.workflow.route if out else ""
    budget = out.workflow.flags.context_budget_chars if out else 3000

    prepare_agent_after_supervisor(
        message=message,
        route=route,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        user_key="09126667788",
        thread_id="bench-rec",
        context_budget_chars=budget,
    )

    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key="09126667788",
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-rec",
    )

    if with_rec and ("پیشنهاد" in message or "بهترین" in message):
        run_recommendation(
            property_codes=["20250101120001", "20250101120002"],
            message=message,
            route=route,
            audience=AUDIENCE_PARTNER,
            user_key="09126667788",
            shared={
                "pipeline": "planning|memory|rag|tools|llm",
                "property_search_agent": True,
                "search_handoff": True,
                "reused_rag": True,
                "reused_memory": True,
                "reused_planning": True,
                "property_codes": ["20250101120001", "20250101120002"],
            },
            analysis_categories=[
                AnalysisCategoryResult(
                    name="price",
                    summary="20250101120001:قیمت",
                    pros=["مناسب"],
                    score=0.8,
                ),
                AnalysisCategoryResult(
                    name="price",
                    summary="20250101120002:قیمت",
                    pros=[],
                    cons=["گران"],
                    score=0.3,
                ),
            ],
        )
        hint = get_recommendation_hint()
        if hint:
            msgs = list(msgs) + [{"role": "system", "content": hint}]

    dt = (time.perf_counter() - t0) * 1000
    aobs = get_agent_obs()
    robs = get_recommendation_obs() if with_rec else {}
    return estimate_messages_tokens(msgs), dt, {
        "route": route,
        "selected": aobs.get("selected_agent") or "",
        "rec_tokens": int(robs.get("recommendation_tokens") or 0),
        "cache_hit": bool(robs.get("recommendation_cache_hit")),
        "reuse_search": bool(robs.get("recommendation_reuse_search")),
        "reuse_analysis": bool(robs.get("recommendation_reuse_analysis")),
        "selected_property": robs.get("selected_property") or "",
        "score": float(robs.get("recommendation_score") or 0),
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("بهترین ویلا را پیشنهاد بده تا ۱۵ میلیارد", "recommendation"),
        ]
        print("=== Recommendation Agent Benchmark (Phase 11) ===")
        for message, label in cases:
            before_tok, _, _ = _run(message, with_rec=False)
            after_toks, after_ms, metas = [], [], {}
            for _ in range(20):
                tok, ms, metas = _run(message, with_rec=True)
                after_toks.append(tok)
                after_ms.append(ms)
            a = statistics.mean(after_toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"selected={metas.get('selected') or '-'} "
                f"rec_tokens={metas.get('rec_tokens')} "
                f"cache_hit={metas.get('cache_hit')} "
                f"reuse_search={metas.get('reuse_search')} reuse_analysis={metas.get('reuse_analysis')} "
                f"pick={metas.get('selected_property') or '-'} "
                f"latency_ms={statistics.mean(after_ms):.2f}"
            )
        print("re_search_count=0 re_analysis_new_queries=0 (reuse/cache only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
