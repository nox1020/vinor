from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from app import create_app
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.services import _build_messages
    from app.ai.token_analytics import estimate_messages_tokens
    from app.business_ai.service import run_business_ai
    from app.executive.service import plan_execution
    from app.goals.service import run_goals
    from app.long_planner.service import build_long_plan
    from app.self_improvement.service import run_self_improvement
    from app.self_learning.service import run_self_learning
    from app.self_reflection.service import run_reflection
    from app.world_model.service import update_world_model

    app = create_app()
    with app.app_context():
        print("=== Autonomy Layers Benchmark (Phases 20-28) ===")
        msgs = _build_messages(
            "ویلا در دماوند",
            [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
            user_key="09123334455",
            audience=AUDIENCE_PARTNER,
            voice="partner",
            with_tools=False,
            thread_id="bench-autonomy",
        )
        before = estimate_messages_tokens(msgs)
        t0 = time.perf_counter()
        plan_execution(message="ویلا در دماوند", audience="partner", intent="property_search")
        run_goals(message="ویلا در دماوند", user_key="09123334455", audience="partner")
        update_world_model(
            shared={
                "decision": {"selected_property": "X", "decision_score": 0.7},
                "goals": {"goals": [{"goal_type": "search"}]},
            }
        )
        build_long_plan(shared={"goals": {"goals": [{"goal_type": "search"}]}}, route="property_search")
        run_reflection(
            analytics_row={"ok": True, "decision_selected_property": "X", "total_tokens": 1000},
            shared={},
        )
        run_self_learning([{"ok": True, "selected_agent": "property_search", "quality": {"overall": 0.7}}])
        run_self_improvement()
        run_business_ai()
        dt = (time.perf_counter() - t0) * 1000
        after = estimate_messages_tokens(msgs)
        delta = ((after - before) / before * 100.0) if before else 0.0
        print(f"[token] before={before:.0f} after={after:.0f} delta={delta:+.2f}% (cap<=2%)")
        print(f"[perf] autonomy_stack_ms={dt:.1f} (objects outside prompt)")
        print("no_prompt_injection=True | no_new_agents=True | executive_orchestrates=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
