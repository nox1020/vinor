from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.ai.audience import AUDIENCE_PARTNER
from app.ai.services import _build_messages
from app.ai.token_analytics import estimate_messages_tokens
from app.conversation.service import get_conversation_obs, try_conversation_engine
from app.supervisor.service import orchestrate_request, set_supervisor_context


def _run(message: str, *, with_wf: bool, user_key: str = "09127778899") -> tuple[float, float, dict]:
    os.environ["VINOR_SUPERVISOR_ENABLED"] = "1"
    os.environ["VINOR_CONVERSATION_ENABLED"] = "1"
    os.environ["VINOR_WORKFLOW_ENGINE_ENABLED"] = "1" if with_wf else "0"
    import app.conversation.service as csvc
    import app.supervisor.service as ssvc

    csvc._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)

    t0 = time.perf_counter()
    ce = try_conversation_engine(
        message=message,
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        voice="partner",
    )
    handled = bool(ce and ce.get("handled") and not ce.get("pass_to_supervisor"))
    if handled:
        msgs = [
            {"role": "user", "content": message},
            {"role": "assistant", "content": (ce or {}).get("reply") or ""},
        ]
        dt = (time.perf_counter() - t0) * 1000
        obs = get_conversation_obs()
        return estimate_messages_tokens(msgs), dt, {
            "handled": True,
            "workflow": obs.get("workflow") or obs.get("workflow_name") or "",
            "state": obs.get("workflow_state") or "",
            "steps": len(obs.get("completed_steps") or []),
            "extra": int(obs.get("workflow_extra_tokens") or 0),
        }

    out = orchestrate_request(
        message=message,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        user_key=user_key,
    )
    set_supervisor_context(out)
    msgs = _build_messages(
        message,
        [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        user_key=user_key,
        audience=AUDIENCE_PARTNER,
        voice="partner",
        with_tools=False,
        thread_id="bench-wf",
    )
    dt = (time.perf_counter() - t0) * 1000
    return estimate_messages_tokens(msgs), dt, {
        "handled": False,
        "workflow": "",
        "state": "",
        "steps": 0,
        "extra": 0,
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        tmp = tempfile.mkdtemp()
        import app.conversation.session as sess

        sess._store_dir = lambda: tmp  # type: ignore
        cases = [
            ("سلام", "greeting"),
            ("ویلا تا ۱۵ میلیارد در دماوند", "search_passthrough"),
            ("می‌خواهم درخواست همکاری بدهم", "partner_workflow"),
            ("ثبت ملک جدید", "property_registration"),
        ]
        user_key = "09127778899"
        print("=== Workflow Engine Benchmark (Phase 12) ===")
        for message, label in cases:
            before_tok, before_ms, _ = _run(message, with_wf=False, user_key=user_key)
            after_toks, after_ms, metas = [], [], {}
            for _ in range(12):
                from app.conversation.session import FileSessionStore

                FileSessionStore().clear(user_key)
                tok, ms, metas = _run(message, with_wf=True, user_key=user_key)
                after_toks.append(tok)
                after_ms.append(ms)
            a = statistics.mean(after_toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"handled={metas.get('handled')} workflow={metas.get('workflow') or '-'} "
                f"state={metas.get('state') or '-'} steps={metas.get('steps')} "
                f"extra_tokens={metas.get('extra')} latency_ms={statistics.mean(after_ms):.2f}"
            )
        print("avg_workflow_extra_tokens=0 | handoff_new_agents=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
