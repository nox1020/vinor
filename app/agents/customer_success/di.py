from __future__ import annotations

from app.agents.customer_success.actions import RuleNextActionBuilder
from app.agents.customer_success.cache import MemoryCustomerSuccessCache
from app.agents.customer_success.conversion import RuleConversionAnalyzer
from app.agents.customer_success.interfaces import CustomerSuccessManager
from app.agents.customer_success.manager import DefaultCustomerSuccessManager
from app.agents.customer_success.planner import RuleFollowUpPlanner


def make_customer_success_manager() -> CustomerSuccessManager:
    return DefaultCustomerSuccessManager(
        planner=RuleFollowUpPlanner(
            conversion=RuleConversionAnalyzer(),
            actions=RuleNextActionBuilder(),
        ),
        cache=MemoryCustomerSuccessCache(),
    )
