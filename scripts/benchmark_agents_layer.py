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
from app.agents.service import prepare_agent_after_supervisor, set_agent_obs, get_agent_obs
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _tokens_for(message: str, *, with_agents: bool) -> tuple[float, float, dict]:
    os.environ["VINOR_SUPERVISOR_ENABLED"] = "1"
    os.environ["VINOR_AGENTS_ENABLED"] = "1" if with_agents else "0"
    import app.agents.service as asvc
    import app.supervisor.service as ssvc

    asvc._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    set_agent_obs(None)

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

    if with_agents:
        prepare_agent_after_supervisor(
            message=message,
            route=route,
            audience=AUDIENCE_PARTNER,
            voice="partner",
            user_key="09126667788",
            thread_id="bench-agents",
            context_budget_chars=budget,
        )
    agent_obs = get_agent_obs() if with_agents else {}

    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key="09126667788",
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-agents",
    )
    dt = (time.perf_counter() - t0) * 1000
    return estimate_messages_tokens(msgs), dt, {
        "route": route,
        "selected_agent": agent_obs.get("selected_agent") or "",
        "skipped_agents": list(agent_obs.get("skipped_agents") or []),
        "agent_tokens": int(agent_obs.get("agent_tokens") or 0),
        "agent_ms": int(agent_obs.get("agent_execution_time_ms") or 0),
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("کار بعدی چیه؟", "follow_up"),
        ]
        print("=== Multi-Agent Phase Benchmark ===")
        for message, label in cases:
            before_tok, before_ms, before_meta = _tokens_for(message, with_agents=False)
            after_toks = []
            after_ms = []
            meta = {}
            for _ in range(20):
                tok, ms, meta = _tokens_for(message, with_agents=True)
                after_toks.append(tok)
                after_ms.append(ms)
            a = statistics.mean(after_toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"selected={meta.get('selected_agent') or '-'} "
                f"agent_tokens={meta.get('agent_tokens')} "
                f"skipped={len(meta.get('skipped_agents') or [])} "
                f"latency_ms={statistics.mean(after_ms):.2f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
