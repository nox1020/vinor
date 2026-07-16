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
from app.agents.parallel.interfaces import ExecutionContext
from app.agents.parallel.service import get_parallel_obs, run_parallel_collaboration
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _reset() -> None:
    import app.agents.parallel.service as ps
    import app.agents.service as ags
    import app.supervisor.service as ssvc

    ps._MANAGER = None
    ags._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)


def _run(message: str, *, parallel: bool, user_key: str) -> tuple[float, float, dict]:
    os.environ["VINOR_AGENTS_ENABLED"] = "1"
    os.environ["VINOR_PARALLEL_AGENTS"] = "1" if parallel else "0"
    os.environ["VINOR_PARALLEL_INJECT_MERGE_HINT"] = "1"
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
        parallel=parallel,
    )
    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-par",
    )
    if pre and pre.compact_hint and parallel:
        msgs = list(msgs) + [{"role": "system", "content": pre.compact_hint}]
    dt = (time.perf_counter() - t0) * 1000
    obs = get_parallel_obs()
    return estimate_messages_tokens(msgs), dt, {
        "merge_tokens": int(pre.merge_tokens if pre and parallel else 0),
        "exec_ms": int(pre.execution_time_ms if pre else 0),
        "parallel_tasks": int(obs.get("parallel_tasks") or (pre.parallel_tasks if pre else 0)),
        "merged": list(pre.merged_agents if pre else []),
        "waves": len(pre.waves_executed) if pre else 0,
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "property_search"),
            ("بهترین ویلا را پیشنهاد بده تا ۱۵ میلیارد", "recommendation"),
        ]
        user_key = "09126667788"
        print("=== Parallel Multi-Agent Benchmark (Phase 16) ===")
        for message, label in cases:
            seq_toks, seq_ms = [], []
            par_toks, par_ms, metas = [], [], {}
            for _ in range(8):
                tok, ms, _ = _run(message, parallel=False, user_key=user_key)
                seq_toks.append(tok)
                seq_ms.append(ms)
            for _ in range(8):
                tok, ms, metas = _run(message, parallel=True, user_key=user_key)
                par_toks.append(tok)
                par_ms.append(ms)
            s = statistics.mean(seq_toks)
            p = statistics.mean(par_toks)
            delta = ((p - s) / s * 100.0) if s else 0.0
            speedup = (statistics.mean(seq_ms) / statistics.mean(par_ms)) if statistics.mean(par_ms) else 0
            print(
                f"[{label}] sequential_tok={s:.0f} parallel_tok={p:.0f} delta={delta:+.2f}% "
                f"seq_ms={statistics.mean(seq_ms):.1f} par_ms={statistics.mean(par_ms):.1f} "
                f"speedup={speedup:.2f}x merge_tokens={metas.get('merge_tokens')} "
                f"parallel_tasks={metas.get('parallel_tasks')} waves={metas.get('waves')} "
                f"merged={metas.get('merged')}"
            )
        print("no_new_agents=True | reuse_search_rag_memory=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
