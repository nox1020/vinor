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
from app.adaptive.service import (
    after_agent_prepare_adaptive,
    after_response_adaptive,
    begin_adaptive,
    clear_adaptive,
    get_adaptive_obs,
)
from app.agents.service import prepare_agent_after_supervisor, set_agent_obs, get_agent_obs
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _run(message: str, *, with_adaptive: bool) -> tuple[float, float, dict]:
    os.environ["VINOR_SUPERVISOR_ENABLED"] = "1"
    os.environ["VINOR_AGENTS_ENABLED"] = "1"
    os.environ["VINOR_ADAPTIVE_ENABLED"] = "1" if with_adaptive else "0"
    import app.adaptive.service as adsvc
    import app.agents.service as asvc
    import app.supervisor.service as ssvc

    adsvc._CONTROLLER = None
    asvc._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)
    set_agent_obs(None)
    clear_adaptive()

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
        thread_id="bench-adaptive",
        context_budget_chars=budget,
    )

    if with_adaptive:
        begin_adaptive(message=message, route=route, audience=AUDIENCE_PARTNER, voice="partner")
        aobs = get_agent_obs()
        after_agent_prepare_adaptive(
            agent_status=str(aobs.get("agent_status") or ""),
            used_components=list(aobs.get("agent_used_components") or []),
            selected_agent=str(aobs.get("selected_agent") or ""),
        )

    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key="09126667788",
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-adaptive",
    )

    # Simulate response evaluation (no LLM) for adaptive path
    fake_reply = "چند گزینه مناسب پیدا شد." if "ویلا" in message else (
        "مرحله بعدی را پیشنهاد می‌کنم." if "کار" in message else "سلام، خوش آمدید!"
    )
    fake_codes = ["T1"] if "ویلا" in message else []
    if with_adaptive:
        after_response_adaptive(reply=fake_reply, land_codes=fake_codes, ok=True)

    dt = (time.perf_counter() - t0) * 1000
    obs = get_adaptive_obs() if with_adaptive else {}
    return estimate_messages_tokens(msgs), dt, {
        "route": route,
        "state": obs.get("workflow_state") or "",
        "confidence": float(obs.get("confidence_score") or 0),
        "retry": int(obs.get("retry_count") or 0),
        "recovery": int(obs.get("recovery_count") or 0),
        "extra_tokens": int(obs.get("adaptive_extra_tokens") or 0),
        "success": (obs.get("workflow_state") == "DONE") if with_adaptive else True,
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("کار بعدی چیه؟", "follow_up"),
        ]
        print("=== Adaptive Execution Phase Benchmark ===")
        success = 0
        retries = 0
        recoveries = 0
        n = 0
        for message, label in cases:
            before_tok, before_ms, _ = _run(message, with_adaptive=False)
            after_toks, after_ms, metas = [], [], {}
            for _ in range(20):
                tok, ms, metas = _run(message, with_adaptive=True)
                after_toks.append(tok)
                after_ms.append(ms)
                n += 1
                if metas.get("success"):
                    success += 1
                retries += int(metas.get("retry") or 0)
                recoveries += int(metas.get("recovery") or 0)
            a = statistics.mean(after_toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"state={metas.get('state')} conf={metas.get('confidence'):.2f} "
                f"retry={metas.get('retry')} recovery={metas.get('recovery')} "
                f"extra_tokens={metas.get('extra_tokens')} "
                f"latency_ms={statistics.mean(after_ms):.2f}"
            )
        print(
            f"summary success_rate={success}/{n} ({100.0 * success / max(n, 1):.1f}%) "
            f"retry_events={retries} recovery_events={recoveries}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
