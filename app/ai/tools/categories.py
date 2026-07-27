"""دسته‌های ابزار — نام ابزار → دسته (بارگذاری مستقل schema از registry)."""
from __future__ import annotations

CATEGORY_ADMIN = "admin"
CATEGORY_PROPERTY = "property"
CATEGORY_FINANCE = "finance"
CATEGORY_SEARCH = "search"
CATEGORY_LEGAL = "legal"
CATEGORY_CRM = "crm"
CATEGORY_OTHER = "other"

# نگاشت ثابت — بدون import سنگین agent_tools
TOOL_CATEGORY: dict[str, str] = {
    "search_lands": CATEGORY_SEARCH,
    "admin_search_lands": CATEGORY_SEARCH,
    "suggest_next_action": CATEGORY_PROPERTY,
    "draft_listing_copy": CATEGORY_PROPERTY,
    "propose_visit_request": CATEGORY_PROPERTY,
    "propose_complete_visit": CATEGORY_PROPERTY,
    "propose_deal": CATEGORY_PROPERTY,
    "propose_release_deal": CATEGORY_PROPERTY,
    "propose_visit_result": CATEGORY_PROPERTY,
    "propose_no_show": CATEGORY_PROPERTY,
    "propose_add_express_listing": CATEGORY_PROPERTY,
    "propose_update_listing_status": CATEGORY_PROPERTY,
    "propose_visit_admin_action": CATEGORY_PROPERTY,
    "propose_offer": CATEGORY_FINANCE,
    "propose_counter_offer": CATEGORY_FINANCE,
    "propose_reservation": CATEGORY_FINANCE,
    "propose_contract": CATEGORY_FINANCE,
    "propose_payment_milestone": CATEGORY_FINANCE,
    "propose_settlement": CATEGORY_FINANCE,
    "propose_commission_action": CATEGORY_FINANCE,
    "admin_ops_summary": CATEGORY_ADMIN,
    "admin_list_queue": CATEGORY_ADMIN,
    "admin_partner_status": CATEGORY_ADMIN,
    "propose_broadcast_sms": CATEGORY_ADMIN,
    "propose_broadcast_push": CATEGORY_ADMIN,
    "propose_partner_decision": CATEGORY_ADMIN,
    "answer_escalation": CATEGORY_ADMIN,
    "propose_log_call": CATEGORY_CRM,
    "propose_followup": CATEGORY_CRM,
    "propose_lead": CATEGORY_CRM,
    "propose_task": CATEGORY_CRM,
    "get_cooperation_info": CATEGORY_OTHER,
    "get_application_status": CATEGORY_OTHER,
    "propose_partner_application": CATEGORY_OTHER,
    "propose_forget_memory": CATEGORY_OTHER,
}


def category_for_tool(name: str) -> str:
    return TOOL_CATEGORY.get(str(name or "").strip(), CATEGORY_OTHER)
