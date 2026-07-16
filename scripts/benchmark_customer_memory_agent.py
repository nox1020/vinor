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
from app.agents.customer_memory.service import get_customer_memory_obs, run_customer_memory
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _baseline(message: str, user_key: str) -> tuple[float, float]:
    os.environ["VINOR_CUSTOMER_MEMORY_ENABLED"] = "0"
    os.environ["VINOR_CUSTOMER_MEMORY_INJECT_HINT"] = "0"
    import app.agents.customer_memory.service as cms
    import app.supervisor.service as ssvc

    cms._MANAGER = None
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
        thread_id="bench-cm-base",
    )
    return estimate_messages_tokens(msgs), (time.perf_counter() - t0) * 1000


def _with_cm(message: str, user_key: str) -> tuple[float, float, dict]:
    os.environ["VINOR_CUSTOMER_MEMORY_ENABLED"] = "1"
    os.environ["VINOR_CUSTOMER_MEMORY_INJECT_HINT"] = "1"
    import app.agents.customer_memory.service as cms
    import app.supervisor.service as ssvc

    cms._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    t0 = time.perf_counter()
    out = orchestrate_request(
        message=message, audience=AUDIENCE_PARTNER, voice="partner", user_key=user_key
    )
    set_supervisor_context(out)
    shared = {
        "memory_prefs": {"budget": "تا ۱۵ میلیارد", "city": "دماوند", "type": "ویلا"},
        "reused_memory": True,
        "reused_planning": True,
    }
    profile = run_customer_memory(
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
        thread_id="bench-cm",
    )
    from app.agents.customer_memory.service import should_run_customer_memory

    if (
        profile
        and profile.compact_hint
        and should_run_customer_memory(message=message)
    ):
        msgs = list(msgs) + [{"role": "system", "content": profile.compact_hint}]
    dt = (time.perf_counter() - t0) * 1000
    obs = get_customer_memory_obs()
    return estimate_messages_tokens(msgs), dt, {
        "cm_tokens": int(profile.customer_memory_tokens if profile else 0)
        if should_run_customer_memory(message=message)
        else 0,
        "build_ms": int(obs.get("profile_build_time_ms") or (profile.profile_build_time_ms if profile else 0)),
        "score": float(obs.get("relationship_score") or 0),
        "prefs": int(obs.get("preference_count") or 0),
        "reuse_mem": bool(obs.get("customer_memory_reuse_memory")),
        "cache": bool(obs.get("customer_memory_cache_hit")),
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("ترجیحات و پروفایل مشتری من چیست؟", "customer_memory"),
        ]
        user_key = "09124445566"
        print("=== Customer Memory Agent Benchmark (Phase 13) ===")
        for message, label in cases:
            before_tok, before_ms = _baseline(message, user_key)
            toks, mss, metas = [], [], {}
            for i in range(12):
                tok, ms, metas = _with_cm(message, user_key)
                toks.append(tok)
                mss.append(ms)
            a = statistics.mean(toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"cm_tokens={metas.get('cm_tokens')} build_ms={metas.get('build_ms')} "
                f"score={metas.get('score')} prefs={metas.get('prefs')} "
                f"reuse_memory={metas.get('reuse_mem')} cache_hit={metas.get('cache')} "
                f"latency_ms={statistics.mean(mss):.2f}"
            )
        print("no_new_memory_store=True | negotiation_followup=skeleton")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
