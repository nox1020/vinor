"""دستهٔ ملک / فروش — نام‌ها برای registry."""
from __future__ import annotations

TOOL_NAMES = frozenset(
    {
        "suggest_next_action",
        "draft_listing_copy",
        "propose_visit_request",
        "propose_complete_visit",
        "propose_deal",
        "propose_release_deal",
        "propose_visit_result",
        "propose_no_show",
        "propose_add_express_listing",
        "propose_update_listing_status",
        "propose_visit_admin_action",
    }
)
