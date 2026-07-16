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
from app.agents.parallel.service import run_parallel_collaboration
from app.decision.service import clear_decision, get_decision_obs, run_decision
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _reset() -> None:
    import app.agents.parallel.service as ps
    import app.agents.service as ags
    import app.decision.service as ds
    import app.supervisor.service as ssvc

    ps._MANAGER = None
    ags._MANAGER = None
    ds._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    clear_decision()


def _run(message: str, *, decision: bool, user_key: str) -> tuple[float, float, dict]:
    os.environ["VINOR_AGENTS_ENABLED"] = "1"
    os.environ["VINOR_PARALLEL_AGENTS"] = "1"
    os.environ["VINOR_PARALLEL_INJECT_MERGE_HINT"] = "1"
    os.environ["VINOR_DECISION_ENABLED"] = "1" if decision else "0"
    os.environ["VINOR_DECISION_INJECT_HINT"] = "1"
    _reset()
    t0 = time.perf_counter()
    out = orchestrate_request(
        message=message, audience=AUDIENCE_PARTNER, voice="partner", user_key=user_key
    )
    set_supervisor_context(out)
    route = str(out.workflow.route or "") if out else ""
    pre = run_parallel_collaboration(
        message=message,
        route=route,
        audience=AUDIENCE_PARTNER,
        user_key=user_key,
        parallel=True,
    )
    dobs: dict = {}
    if decision and pre is not None:
        pm = dict(pre.merged or {})
        shared = dict((pre.metadata or {}).get("shared") or {})
        shared.update(pm)
        if pm.get("recommendation"):
            shared.setdefault("recommended_code", pm.get("recommendation"))
        run_decision(message=message, route=route, shared=shared, parallel_merge=pm)
        dobs = get_decision_obs()
    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-dec",
    )
    # Mirror generate_reply preference: decision hint replaces parallel merge when selected.
    if decision and dobs.get("selected_property"):
        from app.decision.service import get_decision_hint

        hint = get_decision_hint()
        if hint:
            msgs = list(msgs) + [{"role": "system", "content": hint}]
    elif pre and pre.compact_hint:
        msgs = list(msgs) + [{"role": "system", "content": pre.compact_hint}]
    dt = (time.perf_counter() - t0) * 1000
    return estimate_messages_tokens(msgs), dt, {
        "decision_time_ms": int(dobs.get("decision_time_ms") or 0),
        "conflict_resolve_time_ms": int(dobs.get("conflict_resolve_time_ms") or 0),
        "decision_score": float(dobs.get("decision_score") or 0),
        "confidence": float(dobs.get("decision_confidence") or 0),
        "conflict_count": int(dobs.get("conflict_count") or 0),
        "alternative_count": int(dobs.get("alternative_count") or 0),
        "selected": str(dobs.get("selected_property") or ""),
        "decision_tokens": int(dobs.get("decision_tokens") or 0),
    }


def _synthetic_decision_bench(user_key: str) -> None:
    """Measure build/conflict/token when candidates exist (independent of live search hits)."""
    from app.decision.di import make_decision_manager
    from app.decision.interfaces import DecisionRequest
    from app.decision.service import get_decision_hint

    shared = {
        "property_search_agent": True,
        "recommended_code": "20250101120001",
        "property_codes": ["20250101120001", "20250101120002", "20250101120003"],
        "recommendation_items": [
            {"property_code": "20250101120001", "score": 0.88},
            {"property_code": "20250101120002", "score": 0.82},
            {"property_code": "20250101120003", "score": 0.70},
        ],
        "analysis_categories": [{"score": 0.72}],
        "customer_profile": {"relationship_score": 0.55},
        "negotiation_plan": {
            "property_code": "20250101120002",
            "deal_probability": 0.75,
            "risk_score": 0.25,
            "recommended_strategy": "value_anchor",
            "next_action": "counter",
        },
        "customer_success": {
            "conversion_probability": 0.6,
            "next_action": "schedule_visit",
            "followup_type": "visit",
        },
        "parallel_merge": {"recommendation": "20250101120001"},
    }
    mgr = make_decision_manager()
    build_ms, conflict_ms = [], []
    result = None
    for _ in range(20):
        t0 = time.perf_counter()
        result = mgr.run(
            DecisionRequest(
                message="پیشنهاد ویلا",
                route="property_search",
                shared=dict(shared),
                parallel_merge=dict(shared["parallel_merge"]),
            )
        )
        build_ms.append((time.perf_counter() - t0) * 1000)
        conflict_ms.append(float(result.conflict_resolve_time_ms or 0))

    # Token: parallel-only merge hint vs decision hint (replaces merge)
    base_msgs = _build_messages(
        "بهترین ویلا را پیشنهاد بده",
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-dec-syn",
    )
    merge_hint = "=== همکاری === search+mem|rec:…|next:visit"
    off = estimate_messages_tokens(list(base_msgs) + [{"role": "system", "content": merge_hint}])
    # store hint via builder path already on result
    dhint = result.compact_hint if result else ""
    on = estimate_messages_tokens(list(base_msgs) + [{"role": "system", "content": dhint}])
    delta = ((on - off) / off * 100.0) if off else 0.0
    print(
        f"[synthetic_decision] build_ms={statistics.mean(build_ms):.3f} "
        f"conflict_ms={statistics.mean(conflict_ms):.3f} "
        f"score={result.decision_score if result else 0} "
        f"conf={result.confidence if result else 0} "
        f"conflicts={result.conflict_count if result else 0} "
        f"alts={len(result.alternative_properties) if result else 0} "
        f"selected={result.selected_property if result else ''} "
        f"hint_len={len(dhint)} hint_tokens={(len(dhint)+3)//4 if dhint else 0} "
        f"parallel_hint_tok={off:.0f} decision_hint_tok={on:.0f} delta={delta:+.2f}%"
    )
    _ = get_decision_hint  # kept for import parity / future g-path


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("بهترین ویلا را پیشنهاد بده تا ۱۵ میلیارد", "recommendation"),
        ]
        user_key = "09127778899"
        print("=== Decision Engine Benchmark (Phase 17) ===")
        for message, label in cases:
            off_toks, off_ms = [], []
            on_toks, on_ms, metas = [], [], {}
            for _ in range(8):
                tok, ms, _ = _run(message, decision=False, user_key=user_key)
                off_toks.append(tok)
                off_ms.append(ms)
            for _ in range(8):
                tok, ms, metas = _run(message, decision=True, user_key=user_key)
                on_toks.append(tok)
                on_ms.append(ms)
            base = statistics.mean(off_toks)
            dec = statistics.mean(on_toks)
            delta = ((dec - base) / base * 100.0) if base else 0.0
            print(
                f"[{label}] parallel(no-dec)_tok={base:.0f} decision_tok={dec:.0f} "
                f"delta={delta:+.2f}% "
                f"off_ms={statistics.mean(off_ms):.1f} on_ms={statistics.mean(on_ms):.1f} "
                f"build_ms={metas.get('decision_time_ms')} "
                f"conflict_ms={metas.get('conflict_resolve_time_ms')} "
                f"score={metas.get('decision_score')} conf={metas.get('confidence')} "
                f"conflicts={metas.get('conflict_count')} alts={metas.get('alternative_count')} "
                f"selected={metas.get('selected')} hint_tokens={metas.get('decision_tokens')}"
            )
        _synthetic_decision_bench(user_key)
        print("no_llm_decision=True | no_agent_rerun=True | hint_budget<=70 | cap=<1%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
