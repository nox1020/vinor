# -*- coding: utf-8 -*-
"""Static catalogs for agents, tools, prompts, flags (read-only)."""
from __future__ import annotations

import os
from typing import Any, List


def list_agents() -> List[dict[str, Any]]:
    try:
        from app.agents.interfaces import ALL_AGENT_IDS
        from app.agents.config import agents_enabled, property_search_enabled
        from app.supervisor.config import supervisor_enabled
        from app.agents.analysis.config import analysis_enabled
        from app.agents.customer_memory.config import customer_memory_enabled
        from app.agents.recommendation.config import recommendation_enabled
        from app.agents.negotiation.config import negotiation_enabled
        from app.agents.customer_success.config import customer_success_enabled

        master = agents_enabled()
        per_agent = {
            "property_search": (property_search_enabled, "VINOR_PROPERTY_SEARCH_ENABLED"),
            "property_analysis": (analysis_enabled, "VINOR_ANALYSIS_ENABLED"),
            "customer_memory": (customer_memory_enabled, "VINOR_CUSTOMER_MEMORY_ENABLED"),
            "recommendation": (recommendation_enabled, "VINOR_RECOMMENDATION_ENABLED"),
            "negotiation": (negotiation_enabled, "VINOR_NEGOTIATION_ENABLED"),
            "follow_up": (customer_success_enabled, "VINOR_CUSTOMER_SUCCESS_ENABLED"),
        }
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
        per_agent = {}

    rows = []
    for aid in ALL_AGENT_IDS:
        fn_flag = per_agent.get(aid)
        if fn_flag:
            fn, flag_key = fn_flag
            try:
                agent_on = bool(fn())
            except Exception:
                agent_on = True
        else:
            agent_on = True
            flag_key = f"VINOR_AGENT_{aid.upper()}_ENABLED"
        rows.append(
            {
                "id": aid,
                "enabled": bool(master and agent_on),
                "master_enabled": bool(master),
                "agent_enabled": bool(agent_on),
                "flag_hint": flag_key,
                "supervisor_enabled": bool(supervisor_enabled()),
            }
        )
    return rows


TOOL_PHASE_LABELS_FA: dict[str, str] = {
    "core": "هستهٔ فروش",
    "core_partner": "همکار — بازدید و معامله",
    "crm/integration": "CRM و پیگیری",
    "visit_result": "نتیجهٔ بازدید",
    "commercial": "مذاکره و پیشنهاد",
    "closing": "قرارداد و تسویه",
    "admin_ops": "عملیات ادمین",
}

TOOL_DESCRIPTIONS_FA: dict[str, str] = {
    # هستهٔ چت فروش
    "search_lands": "جستجوی فایل‌های سیستم بر اساس معیار خریدار و نمایش کارت پیشنهاد.",
    "suggest_next_action": "پیشنهاد قدم بعدی فروش به همکار (آگهی، بازدید، پیگیری و …).",
    "draft_listing_copy": "نوشتن متن آگهی برای دیوار/اینستا بر اساس فایل.",
    "get_cooperation_info": "توضیح شرایط همکاری و بازاریابی برای مهمان/متقاضی.",
    "get_application_status": "وضعیت درخواست همکاری کاربر را گزارش می‌دهد.",
    "propose_partner_application": "پیشنهاد ثبت درخواست همکاری (نیاز به تأیید کاربر).",
    "propose_forget_memory": "پیشنهاد پاک‌کردن حافظهٔ گفتگو/ترجیحات کاربر (نیاز به تأیید).",
    # بازدید و معامله
    "propose_visit_request": "پیشنهاد ثبت درخواست بازدید برای یک فایل (کارت تأیید).",
    "propose_complete_visit": "پیشنهاد اعلام انجام بازدید (کارت تأیید).",
    "propose_deal": "پیشنهاد شروع/ثبت معامله روی فایل (کارت تأیید).",
    "propose_release_deal": "پیشنهاد لغو یا آزادسازی معامله (کارت تأیید).",
    # CRM
    "propose_log_call": "پیشنهاد ثبت تماس با مشتری در CRM (کارت تأیید).",
    "propose_followup": "پیشنهاد ثبت پیگیری زمان‌بندی‌شده برای مشتری (کارت تأیید).",
    "propose_lead": "پیشنهاد ثبت سرنخ (lead) مشتری (کارت تأیید).",
    "propose_task": "پیشنهاد ثبت کار/تسک برای همکار (کارت تأیید).",
    # نتیجه بازدید
    "propose_visit_result": "پیشنهاد ثبت نتیجهٔ بازدید (علاقه‌مند، رد و …).",
    "propose_no_show": "پیشنهاد ثبت عدم‌حضور در بازدید.",
    # تجاری
    "propose_offer": "پیشنهاد ثبت پیشنهاد قیمت به مشتری.",
    "propose_counter_offer": "پیشنهاد ثبت پیشنهاد متقابل در مذاکره.",
    "propose_reservation": "پیشنهاد رزرو موقت فایل برای مشتری.",
    # بستن معامله
    "propose_contract": "پیشنهاد ثبت قرارداد در مسیر بستن معامله.",
    "propose_payment_milestone": "پیشنهاد ثبت مرحلهٔ پرداخت/قسط.",
    "propose_settlement": "پیشنهاد ثبت تسویهٔ نهایی معامله.",
    # ادمین
    "admin_ops_summary": "خلاصهٔ صف عملیات ادمین: همکار معلق، فایل، بازدید، مالی.",
    "admin_list_queue": "لیست آیتم‌های صف با شناسه/شماره برای اقدام (همکار، فایل معلق، بازدید، پورسانت، برداشت، escalation).",
    "admin_search_lands": "جستجوی فایل‌ها از چت عملیات ادمین.",
    "admin_partner_status": "وضعیت همکار/درخواست همکاری را برای ادمین نشان می‌دهد.",
    "propose_broadcast_sms": "پیشنهاد ارسال پیامک همگانی (نیاز به تأیید ادمین).",
    "propose_broadcast_push": "پیشنهاد ارسال اعلان همگانی (نیاز به تأیید ادمین).",
    "propose_add_express_listing": "پیشنهاد افزودن فایل اکسپرس جدید از چت ادمین.",
    "propose_update_listing_status": "پیشنهاد تغییر وضعیت فایل (تأیید/رد/فروخته و …).",
    "propose_partner_decision": "پیشنهاد تأیید یا رد درخواست همکاری.",
    "propose_visit_admin_action": "پیشنهاد اقدام ادمین روی درخواست بازدید.",
    "propose_commission_action": "پیشنهاد تأیید/رد پورسانت و تأیید/رد/پرداخت برداشت.",
    "answer_escalation": "پاسخ به سوال ارجاع‌شدهٔ AI (escalation) از چت ادمین.",
}


def list_tools() -> List[dict[str, Any]]:
    """Tool names from agent_tools + admin_tools constants."""
    names: list[str] = []
    for mod_path in ("app.ai.agent_tools", "app.ai.admin_tools"):
        try:
            import importlib

            mod = importlib.import_module(mod_path)
            for attr in dir(mod):
                if not attr.startswith("TOOL_"):
                    continue
                val = getattr(mod, attr, None)
                if isinstance(val, str) and val.strip():
                    names.append(val.strip())
        except Exception:
            continue
    names = sorted(set(names))
    out = []
    for n in names:
        phase = _tool_phase(n)
        out.append(
            {
                "name": n,
                "confirm": n.startswith("propose_") or n == "answer_escalation",
                "phase_hint": phase,
                "phase_label_fa": TOOL_PHASE_LABELS_FA.get(phase, phase),
                "description_fa": TOOL_DESCRIPTIONS_FA.get(
                    n, "ابزار چت وینور — توضیح اختصاصی ثبت نشده."
                ),
                "confirm_label_fa": "نیاز به تأیید" if (n.startswith("propose_") or n == "answer_escalation") else "بدون کارت تأیید",
            }
        )
    return out


def _tool_phase(name: str) -> str:
    if name.startswith("admin_") or name in (
        "propose_broadcast_sms",
        "propose_broadcast_push",
        "propose_add_express_listing",
        "propose_update_listing_status",
        "propose_partner_decision",
        "propose_visit_admin_action",
        "propose_commission_action",
        "answer_escalation",
    ):
        return "admin_ops"
    if name in ("propose_log_call", "propose_followup", "propose_lead", "propose_task"):
        return "crm/integration"
    if name in ("propose_visit_result", "propose_no_show"):
        return "visit_result"
    if name in ("propose_offer", "propose_counter_offer", "propose_reservation"):
        return "commercial"
    if name in ("propose_contract", "propose_payment_milestone", "propose_settlement"):
        return "closing"
    if name in (
        "propose_deal",
        "propose_release_deal",
        "propose_complete_visit",
        "propose_visit_request",
    ):
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
    "reach": "رسدکننده و پیگیری",
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
    "VINOR_SUPERVISOR_AGENT_ENABLED": (
        "ایجنت گزارش‌دهنده در چت عملیات ادمین: رویدادهای دامنه "
        "(بازدید، معامله، پیگیری و …) را به‌صورت گزارش فارسی می‌نویسد."
    ),
    "VINOR_AGENTS_ENABLED": (
        "سوئیچ اصلی ایجنت‌های تخصصی فروش (جستجوی فایل، تحلیل، پیشنهاد، مذاکره و …). "
        "خاموش بودن یعنی این لایه‌ها در چت استفاده نمی‌شوند."
    ),
    "VINOR_PARALLEL_AGENTS": (
        "اجرای موازی چند ایجنت تخصصی روی یک درخواست و ادغام نتیجه. "
        "برای سرعت و پوشش بهتر؛ اگر خاموش باشد ایجنت‌ها تک‌به‌تک یا ساده‌تر اجرا می‌شوند."
    ),
    "VINOR_PROPERTY_SEARCH_ENABLED": (
        "ایجنت جستجوی فایل: آماده‌سازی pipeline جستجو "
        "(برنامه‌ریزی، حافظه، RAG، ابزار، LLM) برای پیدا کردن فایل‌های سیستم."
    ),
    "VINOR_ANALYSIS_ENABLED": (
        "ایجنت تحلیل فایل: مقایسه، ارزش خرید و خلاصهٔ مزایا/معایب روی فایل‌های پیدا‌شده."
    ),
    "VINOR_CUSTOMER_MEMORY_ENABLED": (
        "ایجنت حافظهٔ مشتری: ساخت پروفایل از ai_memory "
        "(ترجیح، بودجه، سابقه) برای شخصی‌سازی فروش."
    ),
    "VINOR_RECOMMENDATION_ENABLED": (
        "ایجنت پیشنهاد: رتبه‌بندی نتایج جستجو/تحلیل و پیشنهاد بهترین گزینه به مشتری."
    ),
    "VINOR_NEGOTIATION_ENABLED": (
        "ایجنت مذاکره: برنامهٔ چانه‌زنی و پیشنهاد قیمت "
        "(hint داخلی — متن گفتگو را خودش نمی‌نویسد)."
    ),
    "VINOR_CUSTOMER_SUCCESS_ENABLED": (
        "ایجنت پیگیری / موفقیت مشتری: برنامهٔ اقدام بعدی و چرخهٔ follow-up."
    ),
    "VINOR_REACH_ENABLED": (
        "رسدکننده: پیگیری خودکار خریدار/فروشنده با SMS و اعلان "
        "بدون نیاز به تأیید ادمین در هر نوبت. "
        "ساعت‌های نوبت از همین صفحه (بخش ساعت‌های پیگیری) قابل تنظیم است."
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
        "خاموش بودن دسترسی به این صفحات را قطع می‌کند. فقط با env قابل تغییر است."
    ),
}


def list_ai_flags() -> List[dict[str, Any]]:
    """فلگ‌های AI/OS با مقدار زنده + قابلیت تغییر از پنل."""
    from app.ai_console.flag_settings import (
        MUTABLE_FLAG_KEYS,
        flag_env_locked,
        flag_source,
        get_stored_flags,
    )

    specs = [
        ("VINOR_SUPERVISOR_ENABLED", "supervisor", _try("app.supervisor.config", "supervisor_enabled")),
        ("VINOR_SUPERVISOR_AGENT_ENABLED", "supervisor", _try("app.supervisor_agent.config", "supervisor_agent_enabled")),
        ("VINOR_AGENTS_ENABLED", "agents", _try("app.agents.config", "agents_enabled")),
        ("VINOR_PARALLEL_AGENTS", "agents", _try("app.agents.parallel.config", "parallel_enabled")),
        ("VINOR_PROPERTY_SEARCH_ENABLED", "agents", _try("app.agents.config", "property_search_enabled")),
        ("VINOR_ANALYSIS_ENABLED", "agents", _try("app.agents.analysis.config", "analysis_enabled")),
        ("VINOR_CUSTOMER_MEMORY_ENABLED", "agents", _try("app.agents.customer_memory.config", "customer_memory_enabled")),
        ("VINOR_RECOMMENDATION_ENABLED", "agents", _try("app.agents.recommendation.config", "recommendation_enabled")),
        ("VINOR_NEGOTIATION_ENABLED", "agents", _try("app.agents.negotiation.config", "negotiation_enabled")),
        ("VINOR_CUSTOMER_SUCCESS_ENABLED", "agents", _try("app.agents.customer_success.config", "customer_success_enabled")),
        ("VINOR_REACH_ENABLED", "reach", _try("app.reach.config", "reach_enabled")),
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
    stored = get_stored_flags()
    rows = []
    for name, group, fn in specs:
        val = None
        try:
            val = bool(fn()) if callable(fn) else None
        except Exception:
            val = None
        env_raw = os.environ.get(name)
        source = flag_source(name)
        mutable = name in MUTABLE_FLAG_KEYS
        locked = flag_env_locked(name)
        rows.append(
            {
                "name": name,
                "group": group,
                "group_label_fa": FLAG_GROUP_LABELS_FA.get(group, group),
                "description_fa": FLAG_DESCRIPTIONS_FA.get(name, ""),
                "value": val,
                "env": env_raw,
                "source": source,
                "mutable": mutable,
                "env_locked": locked,
                "stored": stored.get(name) if name in stored else None,
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
