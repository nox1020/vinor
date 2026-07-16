from __future__ import annotations

import os
import statistics
import sys
import time
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.ai.audience import AUDIENCE_PARTNER
from app.ai.services import _build_messages, _prompt_token_parts
from app.ai.token_analytics import estimate_messages_tokens
from app.planning.interfaces import PlanningRequest
from app.planning.service import get_planning_manager, run_planning_once


def main() -> int:
    app = create_app()
    with app.app_context():
        os.environ["VINOR_PLANNING_ENABLED"] = "0"
        import app.planning.service as psvc

        psvc._MANAGER = None

        before = []
        for _ in range(30):
            msgs = _build_messages(
                "ویلا تا ۱۵ میلیارد در دماوند",
                [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
                user_key="09125554433",
                audience=AUDIENCE_PARTNER,
                voice="partner",
                with_tools=False,
                thread_id="bench-plan",
            )
            before.append(estimate_messages_tokens(msgs))

        os.environ["VINOR_PLANNING_ENABLED"] = "1"
        os.environ["VINOR_PLANNING_INJECT_HINT"] = "1"
        os.environ["VINOR_PLANNING_SEED_TOOLS"] = "1"
        psvc._MANAGER = None

        after = []
        plan_ms = []
        with patch(
            "app.ai.agent_tools.run_tool",
            return_value={
                "ok": True,
                "land_codes": ["V-77"],
                "model_result": {"ok": True, "lands": [{"code": "V-77", "title": "ویلا"}]},
            },
        ):
            for _ in range(30):
                t0 = time.perf_counter()
                out = run_planning_once(
                    goal="ویلا تا ۱۵ میلیارد در دماوند",
                    user_key="09125554433",
                    audience=AUDIENCE_PARTNER,
                    voice="partner",
                    chip_intent="find_land",
                )
                plan_ms.append((time.perf_counter() - t0) * 1000)
                msgs = _build_messages(
                    "ویلا تا ۱۵ میلیارد در دماوند",
                    [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
                    user_key="09125554433",
                    audience=AUDIENCE_PARTNER,
                    voice="partner",
                    with_tools=False,
                    thread_id="bench-plan",
                )
                if out and out.compact_hint:
                    msgs.append({"role": "system", "content": out.compact_hint})
                if out and out.seed_messages:
                    msgs.extend(out.seed_messages)
                after.append(estimate_messages_tokens(msgs))

        b = statistics.mean(before)
        a = statistics.mean(after)
        delta = ((a - b) / b * 100.0) if b else 0.0
        print("=== Planning Phase Benchmark ===")
        print(f"Before avg tokens: {b:.2f}")
        print(f"After avg tokens:  {a:.2f}")
        print(f"Token delta: {delta:+.2f}%")
        print(f"Avg planning time ms: {statistics.mean(plan_ms):.2f}")
        mgr = get_planning_manager()
        print(f"Manager active: {mgr is not None}")
        sample = run_planning_once(goal="ویلا مناسب پیشنهاد بده", user_key="09125554433", audience="partner", voice="partner")
        if sample:
            print(f"Sample plan_type={sample.plan.plan_type if sample.plan else ''} tasks={sample.tasks_count} executed={sample.executed_tasks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
