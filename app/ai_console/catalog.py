# -*- coding: utf-8 -*-
"""Static catalogs for agents, tools, prompts, flags (read-only)."""
from __future__ import annotations

import os
from typing import Any, List


def list_agents() -> List[dict[str, Any]]:
    try:
        from app.agents.interfaces import ALL_AGENT_IDS
        from app.agents.config import agents_enabled
        from app.supervisor.config import supervisor_enabled

        master = agents_enabled()
    except Exception:
        ALL_AGENT_IDS = (
            "property_search",
            "property_analysis",
            "customer_memory",
            "recommendation",
            "negotiation",
            "follow_up",
        )
        master = True
        supervisor_enabled = lambda: True  # type: ignore

    rows = []
    for aid in ALL_AGENT_IDS:
        env_key = f"VINOR_AGENT_{aid.upper()}_ENABLED"
        # Most agents use package-level flags; report master + id
        rows.append(
            {
                "id": aid,
                "enabled": bool(master),
                "flag_hint": env_key,
                "supervisor_enabled": bool(supervisor_enabled()),
            }
        )
    return rows


def list_tools() -> List[dict[str, Any]]:
    """Tool names from agent_tools constants."""
    try:
        from app.ai import agent_tools as at

        names = []
        for attr in dir(at):
            if attr.startswith("TOOL_"):
                val = getattr(at, attr, None)
                if isinstance(val, str) and val.strip():
                    names.append(val.strip())
        names = sorted(set(names))
    except Exception:
        names = []
    out = []
    for n in names:
        out.append(
            {
                "name": n,
                "confirm": n.startswith("propose_"),
                "phase_hint": _tool_phase(n),
            }
        )
    return out


def _tool_phase(name: str) -> str:
    if name in ("propose_log_call", "propose_followup", "propose_lead", "propose_task"):
        return "crm/integration"
    if name in ("propose_visit_result", "propose_no_show"):
        return "visit_result"
    if name in ("propose_offer", "propose_counter_offer", "propose_reservation"):
        return "commercial"
    if name in ("propose_contract", "propose_payment_milestone", "propose_settlement"):
        return "closing"
    if name in ("propose_deal", "propose_release_deal", "propose_complete_visit", "propose_visit_request"):
        return "core_partner"
    return "core"


def list_prompts() -> List[dict[str, Any]]:
    try:
        from app.ai import config as cfg

        items = [
            ("public", getattr(cfg, "VINOR_AI_PUBLIC_PROMPT", "") or ""),
            ("partner", getattr(cfg, "VINOR_AI_PARTNER_PROMPT", "") or ""),
            ("special", getattr(cfg, "VINOR_AI_SPECIAL_PROMPT", "") or ""),
        ]
    except Exception:
        items = []
    out = []
    for key, text in items:
        out.append(
            {
                "key": key,
                "chars": len(text),
                "preview": (text[:240] + "…") if len(text) > 240 else text,
                "versioning": False,
                "note": "Read-only from app.ai.config — Prompt Manager versions are future work.",
            }
        )
    return out


# توضیح فارسی گروه‌ها و فلگ‌ها (نمایش در /admin/ai-console/flags)
FLAG_GROUP_LABELS_FA: dict[str, str] = {
    "supervisor": "ناظر و هدایت چت",
    "agents": "ایجنت‌های تخصصی",
    "conversation": "موتور گفتگو",
    "workflow": "گردش‌کار ثبت",
    "memory": "حافظه",
    "evaluation": "ارزیابی کیفیت",
    "bi": "هوش تجاری",
    "foundation": "لایه پایه فعالیت",
    "crm": "ارتباط با مشتری",
    "commercial": "مذاکره و پیشنهاد",
    "closing": "قرارداد و تسویه",
    "integration": "یکپارچه‌سازی",
    "console": "کنسول مانیتور ادمین",
}

FLAG_DESCRIPTIONS_FA: dict[str, str] = {
    "VINOR_SUPERVISOR_ENABLED": (
        "ناظر داخلی چت را روشن می‌کند: مسیر گفتگو، بودجهٔ زمینه، و اینکه "
        "کدام لایه (حافظه، برنامه‌ریزی، جستجو، ابزار) در هر پیام فعال باشد. "
        "بدون UI جدا — فقط هدایت پشت‌صحنه."
    ),
    "VINOR_AGENTS_ENABLED": (
        "سوئیچ اصلی ایجنت‌های تخصصی فروش (جستجوی فایل، تحلیل، پیشنهاد، مذاکره و …). "
        "خاموش بودن یعنی این لایه‌ها در چت استفاده نمی‌شوند."
    ),
    "VINOR_PARALLEL_AGENTS": (
        "اجرای موازی چند ایجنت تخصصی روی یک درخواست و ادغام نتیجه. "
        "برای سرعت و پوشش بهتر؛ اگر خاموش باشد ایجنت‌ها تک‌به‌تک یا ساده‌تر اجرا می‌شوند."
    ),
    "VINOR_CONVERSATION_ENABLED": (
        "موتور گفتگو و نقش‌ها را فعال می‌کند: تشخیص نیت، وضعیت مکالمه، "
        "و هماهنگی فرم‌های ثبت در جریان چت."
    ),
    "VINOR_WORKFLOW_ENGINE_ENABLED": (
        "گردش‌کار ساختاریافتهٔ ثبت (بازدید، معامله، پشتیبانی و …) را روشن می‌کند. "
        "وقتی روشن است، تکمیل فیلدها و ثبت شیء از مسیر تعریف‌شده پیش می‌رود."
    ),
    "VINOR_MEMORY_ENABLED": (
        "حافظهٔ کاربر در چت: ترجیحات، رابطه، و یادداشت‌های بلندمدت. "
        "به ایجنت کمک می‌کند بدون پرسیدن دوباره، معیار و سابقه را به‌خاطر بسپارد."
    ),
    "VINOR_EVALUATION_ENABLED": (
        "لایهٔ ارزیابی کیفیت پاسخ و عملکرد ایجنت. "
        "برای سنجش داخلی است؛ روی مسیر فروش مشتری مستقیم اثر UI ندارد."
    ),
    "VINOR_BI_ENABLED": (
        "هوش تجاری و گزارش‌های تحلیلی عملیات. "
        "داده‌های فروش/عملیات را برای مانیتور و تصمیم جمع می‌کند."
    ),
    "VINOR_FOUNDATION_ENABLED": (
        "لایهٔ پایهٔ Activity و Timeline: ثبت رویدادهای دامنه به‌صورت append-only. "
        "پایهٔ گزارش ناظر عملیات و ردپای پرونده‌هاست."
    ),
    "VINOR_CRM_AI_TOOLS_ENABLED": (
        "ابزارهای چت برای CRM (مخاطب، سرنخ، تماس، پیگیری، کار). "
        "وقتی خاموش باشد، پیشنهاد ثبت CRM از ابزارهای چت دیده نمی‌شود."
    ),
    "VINOR_COMMERCIAL_AI_TOOLS_ENABLED": (
        "ابزارهای چت برای مذاکره، پیشنهاد قیمت، پیشنهاد متقابل و رزرو. "
        "مسیر تجاری قبل از معامله را در چت فعال می‌کند."
    ),
    "VINOR_CLOSING_AI_TOOLS_ENABLED": (
        "ابزارهای چت برای قرارداد، مرحلهٔ پرداخت و تسویه. "
        "مربوط به بستن معامله و مالی پایانی از داخل گفتگوست."
    ),
    "VINOR_INTEGRATION_AI_TOOLS_ENABLED": (
        "ابزارهای چت برای یکپارچه‌سازی با لایه‌های بیرونی/رویدادهای integration. "
        "ثبت و اتصال فعالیت‌های یکپارچه از مسیر چت را کنترل می‌کند."
    ),
    "VINOR_AI_CONSOLE_ENABLED": (
        "کنسول مانیتور ادمین (/admin/ai-console): فلگ‌ها، ابزارها، خطاها و مشاهدهٔ وضعیت AI. "
        "خاموش بودن دسترسی به این صفحات را قطع می‌کند."
    ),
}


def list_ai_flags() -> List[dict[str, Any]]:
    """Sample of AI/OS related flags with live values."""
    specs = [
        ("VINOR_SUPERVISOR_ENABLED", "supervisor", _try("app.supervisor.config", "supervisor_enabled")),
        ("VINOR_AGENTS_ENABLED", "agents", _try("app.agents.config", "agents_enabled")),
        ("VINOR_PARALLEL_AGENTS", "agents", _try("app.agents.parallel.config", "parallel_enabled")),
        ("VINOR_CONVERSATION_ENABLED", "conversation", _try("app.conversation.config", "conversation_enabled")),
        ("VINOR_WORKFLOW_ENGINE_ENABLED", "workflow", _try("app.workflow.config", "workflow_engine_enabled")),
        ("VINOR_MEMORY_ENABLED", "memory", _try("app.memory.config", "memory_enabled")),
        ("VINOR_EVALUATION_ENABLED", "evaluation", _try("app.evaluation.config", "evaluation_enabled")),
        ("VINOR_BI_ENABLED", "bi", _try("app.business_intelligence.config", "bi_enabled")),
        ("VINOR_FOUNDATION_ENABLED", "foundation", _try("app.foundation.config", "foundation_enabled")),
        ("VINOR_CRM_AI_TOOLS_ENABLED", "crm", _try("app.crm.config", "crm_ai_tools_enabled")),
        ("VINOR_COMMERCIAL_AI_TOOLS_ENABLED", "commercial", _try("app.commercial.config", "commercial_ai_tools_enabled")),
        ("VINOR_CLOSING_AI_TOOLS_ENABLED", "closing", _try("app.closing.config", "closing_ai_tools_enabled")),
        ("VINOR_INTEGRATION_AI_TOOLS_ENABLED", "integration", _try("app.integration.config", "integration_ai_tools_enabled")),
        ("VINOR_AI_CONSOLE_ENABLED", "console", _try("app.ai_console.config", "ai_console_enabled")),
    ]
    rows = []
    for name, group, fn in specs:
        val = None
        try:
            val = bool(fn()) if callable(fn) else None
        except Exception:
            val = None
        env_raw = os.environ.get(name)
        rows.append(
            {
                "name": name,
                "group": group,
                "group_label_fa": FLAG_GROUP_LABELS_FA.get(group, group),
                "description_fa": FLAG_DESCRIPTIONS_FA.get(name, ""),
                "value": val,
                "env": env_raw,
                "source": "env" if env_raw is not None else "default",
            }
        )
    return rows


def _try(module: str, attr: str):
    def _fn():
        import importlib

        mod = importlib.import_module(module)
        return getattr(mod, attr)()

    return _fn


def list_workflow_definitions() -> List[dict[str, Any]]:
    try:
        from app.workflow.registry import WorkflowRegistry

        reg = WorkflowRegistry()
        specs = reg.all_specs()
        return [
            {
                "id": s.id,
                "name": s.name,
                "intent": s.intent,
                "steps": len(s.steps or []),
                "pass_through": bool(getattr(s, "pass_through", False)),
            }
            for s in specs
        ]
    except Exception:
        return []
