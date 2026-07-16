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
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _tokens_for(message: str, *, with_supervisor: bool) -> tuple[float, float, dict]:
    os.environ["VINOR_SUPERVISOR_ENABLED"] = "1" if with_supervisor else "0"
    import app.supervisor.service as ssvc

    ssvc._MANAGER = None
    set_supervisor_context(None)

    t0 = time.perf_counter()
    if with_supervisor:
        out = orchestrate_request(
            message=message,
            audience=AUDIENCE_PARTNER,
            voice="partner",
            user_key="09126667788",
        )
        set_supervisor_context(out)
        route = out.workflow.route if out else ""
        skipped = list(out.workflow.skipped) if out else []
        executed = list(out.workflow.executed) if out else []
    else:
        route, skipped, executed = "baseline", [], ["planning", "memory", "rag", "tools", "llm"]

    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key="09126667788",
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-sup",
    )
    dt = (time.perf_counter() - t0) * 1000
    return estimate_messages_tokens(msgs), dt, {
        "route": route,
        "skipped": skipped,
        "executed": executed,
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("کار بعدی چیه؟", "follow_up"),
        ]
        print("=== Supervisor Phase Benchmark ===")
        for message, label in cases:
            before_tok, before_ms, _ = _tokens_for(message, with_supervisor=False)
            after_toks = []
            after_ms = []
            meta = {}
            for _ in range(20):
                tok, ms, meta = _tokens_for(message, with_supervisor=True)
                after_toks.append(tok)
                after_ms.append(ms)
            a = statistics.mean(after_toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            rag_skip = "rag" in (meta.get("skipped") or [])
            mem_skip = "memory" in (meta.get("skipped") or [])
            print(f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                  f"route={meta.get('route')} rag_skipped={rag_skip} memory_skipped={mem_skip} "
                  f"latency_ms={statistics.mean(after_ms):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
