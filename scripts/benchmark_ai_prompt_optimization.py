from __future__ import annotations

import os
import sys
import statistics
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.ai.audience import AUDIENCE_PARTNER
from app.ai.services import _build_messages
from app.ai.token_analytics import estimate_messages_tokens


def _sample_history(n: int = 24) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for i in range(n):
        rows.append({"role": "user", "content": f"پیام کاربر {i} درباره ملک و قیمت در دماوند"})
        rows.append({"role": "assistant", "content": f"پاسخ دستیار {i} با جزئیات فایل و راهنمای بازدید"})
    return rows


def _run_case(*, summary_on: bool) -> dict[str, float]:
    os.environ["VINOR_HISTORY_SUMMARY"] = "1" if summary_on else "0"
    samples_tokens = []
    samples_ms = []
    hist = _sample_history()
    for _ in range(60):
        t0 = time.perf_counter()
        msgs = _build_messages(
            "ویلا تا ۱۵ میلیارد در دماوند",
            hist,
            user_key="09121234567",
            audience=AUDIENCE_PARTNER,
            voice="partner",
            with_tools=True,
            chip_intent="find_land",
            thread_id="bench-thread",
        )
        dt = (time.perf_counter() - t0) * 1000
        samples_ms.append(dt)
        samples_tokens.append(estimate_messages_tokens(msgs))
    return {
        "avg_tokens": statistics.mean(samples_tokens),
        "p95_tokens": sorted(samples_tokens)[int(len(samples_tokens) * 0.95) - 1],
        "avg_ms": statistics.mean(samples_ms),
        "p95_ms": sorted(samples_ms)[int(len(samples_ms) * 0.95) - 1],
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        before = _run_case(summary_on=False)
        after = _run_case(summary_on=True)
        token_drop = ((before["avg_tokens"] - after["avg_tokens"]) / before["avg_tokens"] * 100.0) if before["avg_tokens"] else 0.0
        speed_gain = ((before["avg_ms"] - after["avg_ms"]) / before["avg_ms"] * 100.0) if before["avg_ms"] else 0.0
        print("=== Prompt Optimization Benchmark ===")
        print(f"Before(avg tokens): {before['avg_tokens']:.2f} | After: {after['avg_tokens']:.2f}")
        print(f"Token reduction: {token_drop:.2f}%")
        print(f"Before(avg ms): {before['avg_ms']:.2f} | After: {after['avg_ms']:.2f}")
        print(f"Build speed gain: {speed_gain:.2f}%")
        print(f"P95 tokens before/after: {before['p95_tokens']:.0f} / {after['p95_tokens']:.0f}")
        print(f"P95 ms before/after: {before['p95_ms']:.2f} / {after['p95_ms']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

