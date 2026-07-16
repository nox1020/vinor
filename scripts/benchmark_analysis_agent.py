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
from app.agents.analysis.service import (
    clear_analysis,
    get_analysis_hint,
    get_analysis_obs,
    run_property_analysis,
)
from app.agents.service import prepare_agent_after_supervisor, set_agent_obs, get_agent_obs
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _run(message: str, *, with_analysis: bool) -> tuple[float, float, dict]:
    os.environ["VINOR_SUPERVISOR_ENABLED"] = "1"
    os.environ["VINOR_AGENTS_ENABLED"] = "1"
    os.environ["VINOR_ANALYSIS_ENABLED"] = "1" if with_analysis else "0"
    import app.agents.analysis.service as ansvc
    import app.agents.service as asvc
    import app.supervisor.service as ssvc

    ansvc._MANAGER = None
    asvc._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    set_agent_obs(None)
    clear_analysis()

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
        thread_id="bench-analysis",
        context_budget_chars=budget,
    )

    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key="09126667788",
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-analysis",
    )

    if with_analysis and ("مقایسه" in message or "تحلیل" in message):
        run_property_analysis(
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
        )
        hint = get_analysis_hint()
        if hint:
            msgs = list(msgs) + [{"role": "system", "content": hint}]

    dt = (time.perf_counter() - t0) * 1000
    aobs = get_agent_obs()
    anobs = get_analysis_obs() if with_analysis else {}
    return estimate_messages_tokens(msgs), dt, {
        "route": route,
        "selected": aobs.get("selected_agent") or "",
        "analysis_tokens": int(anobs.get("analysis_tokens") or 0),
        "cache_hit": bool(anobs.get("analysis_cache_hit")),
        "reused_rag": bool(anobs.get("analysis_reused_rag")),
        "reused_memory": bool(anobs.get("analysis_reused_memory")),
        "reused_context": bool(anobs.get("analysis_reused_context")),
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("این دو فایل را مقایسه و تحلیل کن", "property_compare"),
        ]
        print("=== Property Analysis Agent Benchmark (Phase 10) ===")
        for message, label in cases:
            before_tok, before_ms, _ = _run(message, with_analysis=False)
            after_toks, after_ms, metas = [], [], {}
            for i in range(20):
                tok, ms, metas = _run(message, with_analysis=True)
                after_toks.append(tok)
                after_ms.append(ms)
            a = statistics.mean(after_toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"selected={metas.get('selected') or '-'} "
                f"analysis_tokens={metas.get('analysis_tokens')} "
                f"cache_hit={metas.get('cache_hit')} "
                f"reuse_rag={metas.get('reused_rag')} reuse_mem={metas.get('reused_memory')} "
                f"latency_ms={statistics.mean(after_ms):.2f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
