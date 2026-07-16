from __future__ import annotations

import re

from app.agents.interfaces import (
    AGENT_CUSTOMER_MEMORY,
    AGENT_FOLLOW_UP,
    AGENT_NEGOTIATION,
    AGENT_PROPERTY_ANALYSIS,
    AGENT_PROPERTY_SEARCH,
    AGENT_RECOMMENDATION,
    ALL_AGENT_IDS,
    AgentContext,
    AgentRegistry,
    AgentSelection,
    AgentSelector,
)
from app.supervisor.interfaces import (
    ROUTE_PROPERTY_COMPARE,
    ROUTE_PROPERTY_SEARCH,
)

_ANALYSIS_RE = re.compile(
    r"(تحلیل|مقایسه|ارزش خرید|سرمایه.?گذار|مزایا|معایب|کدام بهتر|فرق)",
    re.I,
)
_RECOMMEND_RE = re.compile(
    r"(پیشنهاد|بهترین|مناسب.?من|توصیه|کدوم بخرم|کدام را بخرم|کدام بخرم|recommend)",
    re.I,
)
_CUSTOMER_MEMORY_RE = re.compile(
    r"(ترجیح|پروفایل|سابقه|بودجه.?من|چی دوست|سبک گفتگو|محدودیت|"
    r"رفتار مشتری|شناخت مشتری|customer.?profile|preferences?)",
    re.I,
)
_NEGOTIATION_RE = re.compile(
    r"(مذاکره|چانه|تخفیف|قیمت نهایی|پیشنهاد قیمت|negotiation|bargain|offer\s*price)",
    re.I,
)
_SUCCESS_RE = re.compile(
    r"(پیگیری|فالو.?آپ|follow.?up|اقدام بعدی|بعدا تماس|یادآوری|"
    r"چرخه مشتری|customer.?success|مرحله مشتری)",
    re.I,
)


class RuleAgentSelector(AgentSelector):
    """Supervisor-driven selection including Customer Success / Follow-up (Phase 15)."""

    def __init__(self, registry: AgentRegistry):
        self._registry = registry

    def select(self, *, route: str, ctx: AgentContext) -> AgentSelection:
        route = (route or "").strip()
        msg = (ctx.message or "").strip()
        intent = (ctx.chip_intent or "").strip().lower()
        selected = ""
        reason = "none"

        wants_success = intent in (
            "follow_up",
            "followup",
            "customer_success",
            "nurture",
            "reminder",
        ) or bool(_SUCCESS_RE.search(msg))
        wants_negotiation = intent in (
            "negotiate",
            "negotiation",
            "bargain",
            "discount",
        ) or bool(_NEGOTIATION_RE.search(msg))
        wants_customer_memory = intent in (
            "profile",
            "customer_memory",
            "prefs",
            "preferences",
        ) or bool(_CUSTOMER_MEMORY_RE.search(msg))
        wants_recommendation = intent in ("recommend", "suggestion", "best") or bool(
            _RECOMMEND_RE.search(msg)
        )
        wants_analysis = (
            route == ROUTE_PROPERTY_COMPARE
            or intent in ("analyze", "compare", "analysis")
            or bool(_ANALYSIS_RE.search(msg))
        )

        if wants_success:
            agent = self._registry.get(AGENT_FOLLOW_UP)
            if agent is not None and agent.active:
                selected = AGENT_FOLLOW_UP
                reason = f"customer_success:{route or 'msg'}"
            else:
                reason = "follow_up_inactive"
        elif wants_negotiation:
            agent = self._registry.get(AGENT_NEGOTIATION)
            if agent is not None and agent.active:
                selected = AGENT_NEGOTIATION
                reason = f"negotiation:{route or 'msg'}"
            else:
                reason = "negotiation_inactive"
        elif wants_customer_memory:
            agent = self._registry.get(AGENT_CUSTOMER_MEMORY)
            if agent is not None and agent.active:
                selected = AGENT_CUSTOMER_MEMORY
                reason = f"customer_memory:{route or 'msg'}"
            else:
                reason = "customer_memory_inactive"
        elif wants_recommendation:
            agent = self._registry.get(AGENT_RECOMMENDATION)
            if agent is not None and agent.active:
                selected = AGENT_RECOMMENDATION
                reason = f"recommend:{route or 'msg'}"
            else:
                reason = "recommendation_inactive"
        elif wants_analysis:
            agent = self._registry.get(AGENT_PROPERTY_ANALYSIS)
            if agent is not None and agent.active:
                selected = AGENT_PROPERTY_ANALYSIS
                reason = f"analysis:{route or 'msg'}"
            else:
                reason = "property_analysis_inactive"
        elif route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            agent = self._registry.get(AGENT_PROPERTY_SEARCH)
            if agent is not None and agent.active:
                selected = AGENT_PROPERTY_SEARCH
                reason = f"route:{route}"
            else:
                reason = "property_search_inactive"
        else:
            reason = f"no_agent_for_route:{route or 'empty'}"

        skipped = [aid for aid in ALL_AGENT_IDS if aid != selected]
        return AgentSelection(
            selected_agent=selected,
            skipped_agents=skipped,
            reason=reason,
        )
