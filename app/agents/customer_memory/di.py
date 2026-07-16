from __future__ import annotations

from app.agents.customer_memory.builder import RuleCustomerProfileBuilder
from app.agents.customer_memory.cache import MemoryCustomerProfileCache
from app.agents.customer_memory.interfaces import CustomerMemoryManager
from app.agents.customer_memory.manager import DefaultCustomerMemoryManager
from app.agents.customer_memory.preferences import RulePreferenceExtractor
from app.agents.customer_memory.relationship import RuleRelationshipAnalyzer


def make_customer_memory_manager() -> CustomerMemoryManager:
    return DefaultCustomerMemoryManager(
        extractor=RulePreferenceExtractor(),
        analyzer=RuleRelationshipAnalyzer(),
        builder=RuleCustomerProfileBuilder(),
        cache=MemoryCustomerProfileCache(),
    )
