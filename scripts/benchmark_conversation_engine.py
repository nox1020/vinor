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


def _run(message: str, *, with_ce: bool, user_key: str = "09126667788") -> tuple[float, float, dict]:
    os.environ["VINOR_SUPERVISOR_ENABLED"] = "1"
    os.environ["VINOR_CONVERSATION_ENABLED"] = "1" if with_ce else "0"
    import app.conversation.service as csvc
    import app.supervisor.service as ssvc

    csvc._MANAGER = None
    ssvc._MANAGER = None
    set_supervisor_context(None)

    t0 = time.perf_counter()
    ce_tokens = 0
    handled = False
    if with_ce:
        ce = try_conversation_engine(
            message=message,
            user_key=user_key,
            audience=AUDIENCE_PARTNER,
            voice="partner",
        )
        handled = bool(ce and ce.get("handled") and not ce.get("pass_to_supervisor"))
        ce_tokens = 0  # state outside prompt

    if handled:
        # Early return path — no supervisor message build cost for form steps
        msgs = [{"role": "user", "content": message}, {"role": "assistant", "content": (ce or {}).get("reply") or ""}]
        dt = (time.perf_counter() - t0) * 1000
        obs = get_conversation_obs()
        return estimate_messages_tokens(msgs), dt, {
            "handled": True,
            "workflow": obs.get("workflow") or "",
            "state": obs.get("conversation_state") or "",
            "extra": ce_tokens,
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
        thread_id="bench-ce",
    )
    dt = (time.perf_counter() - t0) * 1000
    return estimate_messages_tokens(msgs), dt, {
        "handled": False,
        "workflow": "",
        "state": "",
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
        ]
        print("=== Conversation Engine Benchmark (Phase 11.5) ===")
        for message, label in cases:
            before_tok, before_ms, _ = _run(message, with_ce=False)
            after_toks, after_ms, metas = [], [], {}
            for _ in range(15):
                tok, ms, metas = _run(message, with_ce=True)
                after_toks.append(tok)
                after_ms.append(ms)
            a = statistics.mean(after_toks)
            delta = ((a - before_tok) / before_tok * 100.0) if before_tok else 0.0
            print(
                f"[{label}] before={before_tok:.0f} after={a:.0f} delta={delta:+.2f}% "
                f"handled={metas.get('handled')} workflow={metas.get('workflow') or '-'} "
                f"state={metas.get('state') or '-'} extra_tokens={metas.get('extra')} "
                f"latency_ms={statistics.mean(after_ms):.2f}"
            )
        print("form_html_removed=False (HTTP forms kept for compatibility; chat is primary)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
