"""تحلیل ۱۰ درخواست نماینده + نمودار ASCII — ai_token_analytics + replay prompt."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from typing import Any

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.ai.agent_tools import tools_schema_for_voice
from app.ai.audience import AUDIENCE_ADMIN, AUDIENCE_PARTNER, AUDIENCE_PUBLIC
from app.ai.services import _build_messages, _prompt_token_parts
from app.ai.token_analytics import estimate_messages_tokens
from app.ai.token_diag import breakdown_prompt_sections, estimate_tools_schema_tokens


def _load_analytics(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _pick_sample(rows: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    if len(rows) <= n:
        return rows[-n:]
    by_aud: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_aud[str(r.get("audience") or "")].append(r)
    sample: list[dict[str, Any]] = []
    for aud in ("public", "partner", "admin"):
        chunk = by_aud.get(aud) or []
        sample.extend(chunk[-max(1, n // 3) :])
    if len(sample) < n:
        sample = rows[-n:]
    return sample[:n]


def _replay_scenarios(app) -> list[dict[str, Any]]:
    """سناریوهای بدون API — تخمین بخش‌ها."""
    scenarios = [
        ("guest_public", "سلام ویلا می‌خوام", None, AUDIENCE_PUBLIC, "public", False, []),
        ("public_tools", "ویلا تا ۱۰ میلیارد", None, AUDIENCE_PUBLIC, "public", True, []),
        (
            "partner_short",
            "فایل مناسب پیشنهاد بده",
            "09125554433",
            AUDIENCE_PARTNER,
            "partner",
            True,
            [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام"}],
        ),
        (
            "partner_long_hist",
            "ادامه بده",
            "09125554433",
            AUDIENCE_PARTNER,
            "partner",
            True,
            [
                {"role": "user", "content": "ویلا دماوند"},
                {"role": "assistant", "content": "چند گزینه دارم"},
                {"role": "user", "content": "بودجه ۱۵"},
                {"role": "assistant", "content": "باشه"},
                {"role": "user", "content": "بازدید"},
                {"role": "assistant", "content": "زمان؟"},
            ],
        ),
        ("lawyer", "قرارداد اجاره چه بندهایی دارد؟", "guest_law", AUDIENCE_PUBLIC, "lawyer", False, []),
        (
            "admin_ops",
            "خلاصه صف عملیات",
            "admin_09120000000",
            AUDIENCE_ADMIN,
            "admin",
            True,
            [],
        ),
    ]
    out: list[dict[str, Any]] = []
    with app.app_context():
        for name, text, key, aud, voice, wt, hist in scenarios:
            msgs = _build_messages(
                text,
                hist or None,
                user_key=key,
                audience=aud,
                voice=voice,
                with_tools=wt,
                thread_id=f"bench-{name}",
            )
            tools = tools_schema_for_voice(voice) if wt and key else []
            bd = breakdown_prompt_sections(msgs, tools=tools or None)
            out.append(
                {
                    "scenario": name,
                    "estimated": True,
                    "input_tokens": bd["estimated_input_tokens"],
                    "output_tokens": 0,
                    **{k: bd.get(k) for k in (
                        "system_total_tokens",
                        "developer_tokens",
                        "history_tokens",
                        "memory_tokens",
                        "rag_context_tokens",
                        "tool_schema_tokens",
                        "user_tokens",
                    )},
                    "flags": bd.get("flags"),
                }
            )
    return out


def _ascii_bar(label: str, value: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return f"{label:12} |"
    fill = int(width * value / total)
    return f"{label:12} |{'#' * fill}{'.' * (width - fill)} {value:5} ({100 * value / total:4.1f}%)"


def main() -> int:
    app = create_app()
    data_dir = os.path.join(app.instance_path, "data")
    analytics_path = os.path.join(data_dir, "ai_token_analytics.jsonl")
    rows = _load_analytics(analytics_path)
    sample = _pick_sample(rows, 10)

    table_rows: list[dict[str, Any]] = []
    for i, r in enumerate(sample, 1):
        inp = int(r.get("input_tokens") or r.get("prompt_tokens") or 0)
        sys_t = int(r.get("system_prompt_tokens") or 0)
        hist = int(r.get("history_tokens") or 0)
        mem = int(r.get("memory_tokens") or 0) + int(r.get("customer_memory_tokens") or 0)
        rag = int(r.get("context_tokens") or r.get("rag_tokens") or 0)
        exec_t = int(r.get("execution_tokens") or 0)
        plan = int(r.get("planning_tokens") or 0)
        out = int(r.get("output_tokens") or 0)
        voice = str(r.get("voice") or r.get("audience") or "public")
        tools_est = max(0, inp - (sys_t + hist + mem + rag + exec_t + plan + int(r.get("user_tokens") or 20)))
        # refine tools from voice if gap huge
        with app.app_context():
            ts = estimate_tools_schema_tokens(tools_schema_for_voice(voice))
        if abs(tools_est - ts) > 400:
            tools_est = ts
        table_rows.append(
            {
                "n": i,
                "audience": r.get("audience"),
                "system": sys_t,
                "developer": 0,
                "history": hist,
                "memory": mem,
                "rag": rag,
                "tools": tools_est,
                "user": max(10, inp - sys_t - hist - mem - rag - tools_est - exec_t - plan),
                "tool_results": exec_t + plan,
                "input": inp,
                "output": out,
                "api_rounds": r.get("api_rounds"),
            }
        )

    if len(table_rows) < 10:
        replays = _replay_scenarios(app)
        for j, rp in enumerate(replays[: 10 - len(table_rows)], start=len(table_rows) + 1):
            table_rows.append(
                {
                    "n": j,
                    "audience": rp.get("scenario"),
                    "system": int(rp.get("system_total_tokens") or 0),
                    "developer": int(rp.get("developer_tokens") or 0),
                    "history": int(rp.get("history_tokens") or 0),
                    "memory": int(rp.get("memory_tokens") or 0),
                    "rag": int(rp.get("rag_context_tokens") or 0),
                    "tools": int(rp.get("tool_schema_tokens") or 0),
                    "user": int(rp.get("user_tokens") or 0),
                    "tool_results": 0,
                    "input": int(rp.get("input_tokens") or 0),
                    "output": 0,
                    "api_rounds": 1,
                    "estimated": True,
                }
            )

    chart_path = os.path.join(data_dir, "ai_token_chart_data.json")
    os.makedirs(data_dir, exist_ok=True)
    with open(chart_path, "w", encoding="utf-8") as f:
        json.dump({"requests": table_rows[:10]}, f, ensure_ascii=False, indent=2)

    print("=== 10-Request Token Table (analytics + replay) ===")
    hdr = f"{'#':>2} {'Aud':^12} {'Sys':>5} {'Dev':>4} {'Hist':>5} {'Mem':>4} {'RAG':>4} {'Tools':>5} {'User':>4} {'In':>5} {'Out':>4} Rnd"
    print(hdr)
    for row in table_rows[:10]:
        print(
            f"{row['n']:2} {str(row['audience'])[:12]:^12} "
            f"{row['system']:5} {row['developer']:4} {row['history']:5} {row['memory']:4} "
            f"{row['rag']:4} {row['tools']:5} {row['user']:4} {row['input']:5} {row['output']:4} "
            f"{row.get('api_rounds') or 1}"
        )

    print("\n=== ASCII chart (request #1) ===")
    if table_rows:
        r0 = table_rows[0]
        tot = int(r0["input"]) or 1
        for label, key in (
            ("System", "system"),
            ("History", "history"),
            ("Memory", "memory"),
            ("RAG", "rag"),
            ("Tools", "tools"),
            ("User", "user"),
            ("ToolRes", "tool_results"),
        ):
            print(_ascii_bar(label, int(r0[key]), tot))

    # growth check
    by_user: dict[str, list[int]] = defaultdict(list)
    for r in rows[-40:]:
        by_user[str(r.get("user") or "")].append(int(r.get("input_tokens") or 0))
    unbounded = [
        u for u, vals in by_user.items() if len(vals) >= 3 and vals[-1] > vals[0] * 1.35
    ]
    print("\nUnbounded context growth (last 40 rows, >35% climb):", unbounded[:5] or "none detected")
    print("Chart data:", chart_path)

    breakdown_path = os.path.join(data_dir, "ai_token_breakdown.jsonl")
    bd_rows = _load_analytics(breakdown_path)
    if bd_rows:
        recent = bd_rows[-200:]
        with_sent = [r for r in recent if "tools_sent_count" in r]
        if with_sent:
            le3 = sum(1 for r in with_sent if int(r.get("tools_sent_count") or 0) <= 3)
            pct = 100.0 * le3 / len(with_sent)
            print(
                f"\n=== Per-round tools (breakdown log, last {len(with_sent)} rows with tools_sent_count) ==="
            )
            print(f"  requests with <=3 tools in schema: {le3}/{len(with_sent)} ({pct:.1f}%)")
            if pct < 90.0:
                print("  NOTE: target is >90% with 1-3 tools; tune selection or check VINOR_AI_PER_ROUND_TOOLS")
        else:
            print("\n(breakdown log has no tools_sent_count yet — run live chats with VINOR_AI_TOKEN_DIAG=1)")

    profile_path = os.path.join(data_dir, "ai_payload_profile.jsonl")
    prof_rows = _load_analytics(profile_path)
    if prof_rows:
        last = prof_rows[-1]
        shares = last.get("shares_pct") or {}
        delta = last.get("delta_round0_round1")
        print(f"\n=== Payload profiler (last row, {profile_path}) ===")
        print("  shares_pct:", json.dumps(shares, ensure_ascii=False))
        if isinstance(delta, dict):
            print(
                "  delta_round0_round1 total:",
                delta.get("total_payload_tokens"),
                "| history:",
                delta.get("history_tokens"),
                "| tool_result:",
                delta.get("tool_result_tokens"),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
