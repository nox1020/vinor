from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.planning.interfaces import Executor, PlanningRequest, Task, TaskResult

# Tools safe to pre-execute without waiting for LLM / multi-step forms.
_EXECUTABLE_TOOLS = frozenset(
    {
        "search_lands",
        "get_cooperation_info",
        "get_application_status",
        "suggest_next_action",
        "draft_listing_copy",
    }
)


class ToolExecutor(Executor):
    """Executes plan tasks using ONLY existing agent tools."""

    def execute_task(self, task: Task, *, req: PlanningRequest) -> TaskResult:
        name = (task.tool_name or "").strip()
        if not name:
            # Local/no-tool task (analyze/rank/compose) — mark done.
            return TaskResult(task_id=task.id, ok=True, tool_name="", model_result={"ok": True, "local": True})
        if name not in _EXECUTABLE_TOOLS:
            return TaskResult(
                task_id=task.id,
                ok=True,
                tool_name=name,
                model_result={"ok": True, "delegated": True},
            )
        try:
            from app.ai.agent_tools import run_tool

            out = run_tool(
                name,
                dict(task.tool_args or {}),
                phone=req.user_key,
                audience=req.audience,
                voice=req.voice,
                thread_id=req.thread_id,
            )
        except Exception as exc:
            return TaskResult(task_id=task.id, ok=False, tool_name=name, error=str(exc))

        model_result = out.get("model_result")
        if not isinstance(model_result, dict):
            model_result = {"ok": bool(out.get("ok")), "error": out.get("error")}
        ui = out.get("ui_action") if isinstance(out.get("ui_action"), dict) else None
        codes = [str(c).strip() for c in (out.get("land_codes") or []) if str(c).strip()]
        if not codes and isinstance(model_result.get("lands"), list):
            for row in model_result["lands"]:
                if isinstance(row, dict):
                    c = str(row.get("code") or "").strip()
                    if c:
                        codes.append(c)
        return TaskResult(
            task_id=task.id,
            ok=bool(out.get("ok")),
            tool_name=name,
            model_result=model_result,
            ui_action=ui,
            land_codes=codes[:5],
            error=str(out.get("error") or ""),
        )


def build_seed_messages(results: list[TaskResult]) -> list[dict[str, Any]]:
    """Convert executed tool results into OpenAI-style tool messages for agent loop."""
    tool_calls = []
    tool_msgs = []
    for i, r in enumerate(results):
        if not r.tool_name or r.tool_name not in _EXECUTABLE_TOOLS:
            continue
        if r.model_result.get("delegated") or r.model_result.get("local"):
            continue
        tc_id = f"plan_call_{i}_{uuid4().hex[:8]}"
        tool_calls.append(
            {
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": r.tool_name,
                    "arguments": "{}",
                },
            }
        )
        try:
            content = json.dumps(r.model_result, ensure_ascii=False)[:1800]
        except Exception:
            content = str(r.model_result)[:1800]
        tool_msgs.append({"role": "tool", "tool_call_id": tc_id, "content": content})
    if not tool_calls:
        return []
    return [
        {
            "role": "assistant",
            "content": None,
            # DeepSeek thinking mode rejects tool_calls turns without this field.
            "reasoning_content": "",
            "tool_calls": tool_calls,
        },
        *tool_msgs,
    ]
