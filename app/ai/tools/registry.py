"""رجیستری ابزار چت — نام، schema، handler، لحن‌های مجاز، نیاز به تأیید.

منبع حقیقت مجوز همان `app/ai/goal.py` است (CORE_TOOLS_*)؛ این ماژول همان‌ها را
به یک جدول قابل‌پرس‌وجو تبدیل می‌کند تا selection/assistant/کنسول ادمین به
جای حدس زدن، از یک جا بخوانند. اجرای واقعی به `agent_tools.run_tool` و
`admin_tools.run_admin_tool` می‌رسد و مجوز دوباره همان‌جا بررسی می‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.ai.audience import (
    VOICE_ADMIN,
    VOICE_LAWYER,
    VOICE_PARTNER,
    VOICE_PUBLIC,
    VOICE_SPECIAL,
)
from app.ai.goal import (
    CORE_TOOLS_ADMIN,
    CORE_TOOLS_PARTNER,
    CORE_TOOLS_PUBLIC,
    EXTENDED_CHAT_TOOLS,
)

from .categories import category_for_tool

SALES_VOICES = frozenset({VOICE_PARTNER, VOICE_SPECIAL})
ALL_SALES_VOICES = frozenset({VOICE_PUBLIC, VOICE_PARTNER, VOICE_SPECIAL})

ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """یک ابزار چت — بدون منطق کسب‌وکار، فقط شناسنامه."""

    name: str
    category: str
    allowed_voices: frozenset[str]
    requires_confirmation: bool
    in_llm_catalog: bool

    def allows(self, voice: str | None) -> bool:
        v = (voice or "").strip().lower()
        return v in self.allowed_voices


def _requires_confirmation(name: str) -> bool:
    """ابزارهای propose_* کارت تأیید می‌سازند و بدون تأیید کاربر چیزی ثبت نمی‌کنند."""
    return str(name or "").startswith("propose_")


def _build_registry() -> dict[str, ToolSpec]:
    voices_for: dict[str, set[str]] = {}
    for name in CORE_TOOLS_PUBLIC:
        voices_for.setdefault(name, set()).add(VOICE_PUBLIC)
    for name in CORE_TOOLS_PARTNER:
        voices_for.setdefault(name, set()).update(SALES_VOICES)
    for name in CORE_TOOLS_ADMIN:
        voices_for.setdefault(name, set()).add(VOICE_ADMIN)
    # EXTENDED در run_tool زنده است (کارت/مسیر قدیمی) اما به کاتالوگ LLM نمی‌رود.
    for name in EXTENDED_CHAT_TOOLS:
        voices_for.setdefault(name, set()).update(SALES_VOICES)

    out: dict[str, ToolSpec] = {}
    for name, voices in voices_for.items():
        out[name] = ToolSpec(
            name=name,
            category=category_for_tool(name),
            allowed_voices=frozenset(voices),
            requires_confirmation=_requires_confirmation(name),
            in_llm_catalog=name not in EXTENDED_CHAT_TOOLS,
        )
    return out


_REGISTRY: dict[str, ToolSpec] = _build_registry()


def get_tool(name: str) -> ToolSpec | None:
    return _REGISTRY.get(str(name or "").strip())


def list_tools() -> list[ToolSpec]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def tool_names_for_voice(voice: str | None, *, llm_only: bool = True) -> list[str]:
    """نام ابزارهای مجاز یک لحن — وکیل ملکی ابزار ندارد."""
    v = (voice or "").strip().lower()
    if v == VOICE_LAWYER:
        return []
    return sorted(
        spec.name
        for spec in _REGISTRY.values()
        if spec.allows(v) and (spec.in_llm_catalog or not llm_only)
    )


def is_allowed(name: str, voice: str | None) -> bool:
    spec = get_tool(name)
    return bool(spec and spec.allows(voice))


def requires_confirmation(name: str) -> bool:
    spec = get_tool(name)
    return bool(spec and spec.requires_confirmation)


def execute(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    phone: str,
    audience: str | None,
    voice: str | None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """اجرای ابزار — مجوز در `run_tool` هم دوباره بررسی می‌شود (لایهٔ دوم عمدی)."""
    from app.ai.agent_tools import run_tool

    return run_tool(
        name,
        arguments,
        phone=phone,
        audience=audience,
        voice=voice,
        thread_id=thread_id,
    )


# --- schema helpers (سازگاری با selection / token_diag) --------------------


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
