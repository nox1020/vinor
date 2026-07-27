"""بارگذاری تنبل schema بر اساس دسته — فیلتر روی کاتالوگ voice."""
from __future__ import annotations

from typing import Any

from .categories import category_for_tool


def _schema_tool_name(schema: dict[str, Any]) -> str:
    fn = schema.get("function") if isinstance(schema.get("function"), dict) else {}
    return str(fn.get("name") or "").strip()


def full_catalog_for_voice(voice: str | None) -> list[dict[str, Any]]:
    from app.ai.agent_tools import tools_schema_for_voice

    return list(tools_schema_for_voice(voice) or [])


def schemas_for_tool_names(
    voice: str | None,
    names: set[str] | frozenset[str],
) -> list[dict[str, Any]]:
    want = {str(n).strip() for n in names if str(n).strip()}
    if not want:
        return []
    full = full_catalog_for_voice(voice)
    return [s for s in full if _schema_tool_name(s) in want]


def schemas_for_categories(
    voice: str | None,
    categories: set[str],
) -> list[dict[str, Any]]:
    if not categories:
        return []
    full = full_catalog_for_voice(voice)
    return [s for s in full if category_for_tool(_schema_tool_name(s)) in categories]
