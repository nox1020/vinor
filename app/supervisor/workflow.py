from __future__ import annotations

from app.supervisor.interfaces import ComponentFlags, Workflow


def build_workflow(route: str, flags: ComponentFlags, *, reason: str = "") -> Workflow:
    components = {
        "planning": flags.use_planning,
        "memory": flags.use_memory,
        "rag": flags.use_rag,
        "tools": flags.use_tools,
        "llm": flags.use_llm,
    }
    executed = [name for name, on in components.items() if on]
    skipped = [name for name, on in components.items() if not on]
    return Workflow(
        route=route,
        flags=flags,
        reason=reason or route,
        executed=executed,
        skipped=skipped,
        metadata={"lazy": True},
    )
