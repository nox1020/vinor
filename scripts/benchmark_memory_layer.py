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
from app.ai.token_analytics import estimate_messages_tokens, estimate_tokens
from app.memory.interfaces import MemoryExtractRequest
from app.memory.service import get_memory_provider, learn_from_exchange


def _history() -> list[dict[str, str]]:
    return [
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "سلام، چطور کمک کنم؟"},
        {"role": "user", "content": "ویلا می‌خوام"},
        {"role": "assistant", "content": "بودجه و منطقه را بگو"},
    ]


def main() -> int:
    app = create_app()
    with app.app_context():
        os.environ["VINOR_MEMORY_ENABLED"] = "0"
        # Reset provider singleton for clean A/B
        import app.memory.service as memsvc

        memsvc._PROVIDER = None

        before_tokens = []
        before_ms = []
        for _ in range(40):
            t0 = time.perf_counter()
            msgs = _build_messages(
                "ویلا تا ۱۵ میلیارد در دماوند",
                _history(),
                user_key="09129998877",
                audience=AUDIENCE_PARTNER,
                voice="partner",
                with_tools=False,
                thread_id="bench-mem",
            )
            before_ms.append((time.perf_counter() - t0) * 1000)
            before_tokens.append(estimate_messages_tokens(msgs))

        os.environ["VINOR_MEMORY_ENABLED"] = "1"
        os.environ["VINOR_MEMORY_BUDGET_CHARS"] = "280"
        memsvc._PROVIDER = None
        # Seed memory
        learn_from_exchange(
            user_key="09129998877",
            user_message="ویلا تا ۱۵ میلیارد در دماوند می‌خوام",
            assistant_reply="چند فایل در گرمابسرد دارم",
            audience=AUDIENCE_PARTNER,
            land_codes=["V-101"],
        )

        after_tokens = []
        after_ms = []
        mem_toks = []
        for _ in range(40):
            t0 = time.perf_counter()
            msgs = _build_messages(
                "ویلا تا ۱۵ میلیارد در دماوند",
                _history(),
                user_key="09129998877",
                audience=AUDIENCE_PARTNER,
                voice="partner",
                with_tools=False,
                thread_id="bench-mem",
            )
            after_ms.append((time.perf_counter() - t0) * 1000)
            after_tokens.append(estimate_messages_tokens(msgs))
            mem_block = ""
            for m in msgs:
                c = str(m.get("content") or "")
                if "=== حافظه مرتبط کاربر ===" in c:
                    mem_block = c
                    break
            mem_toks.append(estimate_tokens(mem_block) if mem_block else 0)

        b = statistics.mean(before_tokens)
        a = statistics.mean(after_tokens)
        delta = ((a - b) / b * 100.0) if b else 0.0
        print("=== Memory Phase Benchmark ===")
        print(f"Before avg tokens: {b:.2f}")
        print(f"After avg tokens:  {a:.2f}")
        print(f"Token delta: {delta:+.2f}%")
        print(f"Avg memory tokens injected: {statistics.mean(mem_toks):.2f}")
        print(f"Before avg ms: {statistics.mean(before_ms):.2f}")
        print(f"After avg ms:  {statistics.mean(after_ms):.2f}")
        provider = get_memory_provider()
        print(f"Provider active: {provider is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
