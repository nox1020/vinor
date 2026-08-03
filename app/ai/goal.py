"""هدف قفل‌شدهٔ ایجنت Vinor — منبع حقیقت کد.

سند: roadmap/AGENT_GOAL.md

یک ایجنت = یک بازاریاب فروش.
فقط فایل‌های داخل سیستم را از چت می‌فروشد.
"""
from __future__ import annotations

# --- هویت ---
AGENT_IDENTITY = "marketer"  # تنها هویت محصول
AGENT_ROLE_FA = "بازاریاب فروش وینور"

GOAL_ONE_LINER = (
    "وینور یک ایجنت بازاریاب دارد که فقط فایل‌های داخل سیستم را می‌فروشد: "
    "به مشتری بهترین گزینه را پیشنهاد می‌دهد و تا معامله پیگیری می‌کند؛ "
    "بازاریاب استخدام می‌کند و هر روز کمک‌شان می‌کند بفروشند."
)

# متن system — اول هر prompt
GOAL_SYSTEM = (
    "تو یک بازاریاب فروش وینور هستی. فقط فایل‌های داخل سیستم (گرمابسرد دماوند) را می‌فروشی: "
    "به مشتری بهترین گزینه را پیشنهاد می‌دهی و تا معامله پیگیری می‌کنی؛ "
    "بازاریاب استخدام می‌کنی و هر روز کمک‌شان می‌کنی بفروشند. "
    "محل کارت همین چت است — راهنمای سایت نیستی. "
    "یک نفر هستی؛ چند ایجنت جدا نیستی. "
    "لحن: خودمونی و کوتاه مثل پیامک بانکی؛ جواب ۱ تا ۳ جمله؛ فقط یک قدم بعدی؛ حاشیه نرو."
)

GOAL_HINT_PREFIX = "یادآوری داخلی (یک بازاریاب؛ به کاربر نگو چندایجنتی): "

VISIT_COORD_PHONE = "09121471301"
GEO_SCOPE_FA = "استان تهران، شهرستان دماوند، روستای گرمابسرد"

# ابزارهای هستهٔ چت — فقط این‌ها در schema ایجنت می‌آیند
CORE_TOOLS_PUBLIC = frozenset(
    {
        "search_lands",
        "get_cooperation_info",
        "get_application_status",
        "propose_partner_application",
        "propose_forget_memory",
    }
)

CORE_TOOLS_PARTNER = frozenset(
    {
        "search_lands",
        "suggest_next_action",
        "draft_listing_copy",
        "propose_visit_request",
        "propose_complete_visit",
        "propose_deal",
        "propose_release_deal",
        "propose_log_call",
        "propose_followup",
        "propose_forget_memory",
    }
)

GOAL_ADMIN_SYSTEM = (
    "تو دستیار عملیات وینور هستی — پنل ادمین. "
    "فروش به مشتری نمی‌کنی؛ فایل، همکار، بازدید، مالی و پیام همگانی را با ابزار + کارت تأیید جلو می‌بری. "
    "برای دیدن صف از admin_ops_summary یا admin_list_queue استفاده کن؛ لینک صفحه نده. "
    "پاسخ کوتاه و هدف‌محور؛ فقط یک اقدام بعدی."
)

CORE_TOOLS_ADMIN = frozenset(
    {
        "admin_ops_summary",
        "admin_search_lands",
        "admin_partner_status",
        "admin_list_queue",
        "propose_broadcast_sms",
        "propose_broadcast_push",
        "propose_add_express_listing",
        "propose_update_listing_status",
        "propose_partner_decision",
        "propose_visit_admin_action",
        "propose_commission_action",
        "answer_escalation",
    }
)

# در کد می‌مانند برای کارت/مسیرهای قدیمی؛ به مدل چت داده نمی‌شوند
EXTENDED_CHAT_TOOLS = frozenset(
    {
        "propose_visit_result",
        "propose_no_show",
        "propose_offer",
        "propose_counter_offer",
        "propose_reservation",
        "propose_contract",
        "propose_payment_milestone",
        "propose_settlement",
        "propose_lead",
        "propose_task",
    }
)


def wrap_internal_hint(text: str | None) -> str:
    """Hintهای داخلی را زیر هویت تک‌بازاریاب نگه دار."""
    t = str(text or "").strip()
    if not t:
        return ""
    if t.startswith(GOAL_HINT_PREFIX):
        return t
    return GOAL_HINT_PREFIX + t


def single_marketer_chat_enabled() -> bool:
    """هویت محصول = یک بازاریاب؛ hint چندایجنت به messages نرود (پیش‌فرض ON)."""
    import os

    return (os.environ.get("VINOR_SINGLE_MARKETER_CHAT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_core_tool(name: str, *, voice: str | None = None) -> bool:
    n = str(name or "").strip()
    v = (voice or "").strip().lower()
    if v == "admin":
        return n in CORE_TOOLS_ADMIN
    if v in ("partner", "special"):
        return n in CORE_TOOLS_PARTNER
    return n in CORE_TOOLS_PUBLIC


def serves_sales_goal(change_summary: str) -> bool:
    """قانون تصمیم سریع برای تغییرات آینده (مستند در کد)."""
    _ = change_summary
    return True
