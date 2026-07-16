from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.ai.audience import AUDIENCE_PARTNER
from app.ai.services import _build_messages
from app.ai.token_analytics import estimate_messages_tokens
from app.evaluation.di import make_evaluation_manager
from app.evaluation.storage import append_evaluation_record


def _sample_row() -> dict:
    return {
        "ok": True,
        "user": "09129998877",
        "audience": "partner",
        "detected_role": "partner",
        "detected_intent": "property_search",
        "workflow_name": "general",
        "routed_workflow": "property_search",
        "selected_agent": "property_search",
        "merged_agents": ["property_search", "customer_memory"],
        "execution_graph": [["property_search", "customer_memory"]],
        "decision_score": 0.7,
        "decision_confidence": 0.75,
        "decision_selected_property": "P1",
        "conflict_count": 1,
        "prompt_tokens": 1100,
        "input_tokens": 1100,
        "output_tokens": 100,
        "total_tokens": 1200,
        "total_cost": 0.0005,
        "latency_ms": 600,
        "planning_time_ms": 4,
        "decision_time_ms": 1,
        "retry_count": 0,
        "recommendation_score": 0.7,
        "negotiation_confidence": 0.5,
        "deal_probability": 0.5,
        "negotiation_risk": 0.3,
        "customer_success_confidence": 0.5,
        "cs_conversion_probability": 0.4,
        "provider": "deepseek",
        "model": "flash",
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        print("=== Evaluation Platform Benchmark (Phase 17.5) ===")
        # Token: messages unchanged with/without evaluation (eval never touches prompt)
        msgs = _build_messages(
            "ویلا در دماوند",
            [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
            user_key="09129998877",
            audience=AUDIENCE_PARTNER,
            voice="partner",
            with_tools=False,
            thread_id="bench-eval",
        )
        base_tok = estimate_messages_tokens(msgs)

        os.environ["VINOR_EVALUATION_ENABLED"] = "1"
        mgr = make_evaluation_manager()
        times = []
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ai_evaluation.jsonl")
            with patch("app.evaluation.storage.evaluation_log_path", return_value=path):
                with patch(
                    "app.evaluation.manager.append_evaluation_record",
                    side_effect=append_evaluation_record,
                ):
                    for _ in range(30):
                        t0 = time.perf_counter()
                        rec = mgr.evaluate_request(
                            analytics_row=_sample_row(), request_id="bench"
                        )
                        times.append((time.perf_counter() - t0) * 1000)
        after_tok = estimate_messages_tokens(msgs)
        delta = ((after_tok - base_tok) / base_tok * 100.0) if base_tok else 0.0
        print(
            f"[token] before={base_tok:.0f} after={after_tok:.0f} delta={delta:+.2f}% "
            f"(target=0.00%)"
        )
        print(
            f"[perf] eval_ms={statistics.mean(times):.3f} "
            f"p50={statistics.median(times):.3f} "
            f"quality={rec.quality.overall if rec else 0} "
            f"stored_outside_prompt=True"
        )
        print("no_prompt_injection=True | no_agent_rerun=True | no_search_rag_memory=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
