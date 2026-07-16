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
)
from app.agents.parallel.graph import StaticDependencyGraphBuilder, waves_for_subset
from app.agents.parallel.interfaces import ExecutionContext, ExecutionPlan, ExecutionPlanner
from app.supervisor.interfaces import ROUTE_PROPERTY_COMPARE, ROUTE_PROPERTY_SEARCH

_ANALYSIS_RE = re.compile(
    r"(تحلیل|مقایسه|ارزش خرید|سرمایه.?گذار|مزایا|معایب|کدام بهتر|فرق)",
    re.I,
)
_RECOMMEND_RE = re.compile(
    r"(پیشنهاد|بهترین|مناسب.?من|توصیه|کدوم بخرم|کدام را بخرم|کدام بخرم|recommend)",
    re.I,
)
_NEGOTIATION_RE = re.compile(
    r"(مذاکره|چانه|تخفیف|قیمت نهایی|پیشنهاد قیمت|negotiation|bargain)",
    re.I,
)
_SUCCESS_RE = re.compile(
    r"(پیگیری|فالو.?آپ|follow.?up|اقدام بعدی|یادآوری|customer.?success)",
    re.I,
)
_MEMORY_RE = re.compile(
    r"(ترجیح|پروفایل|سابقه|بودجه.?من|شناخت مشتری|preferences?)",
    re.I,
)
_SEARCH_RE = re.compile(r"(ویلا|زمین|باغ|ملک|فایل|پیدا|جستجو|بودجه)", re.I)


class RuleExecutionPlanner(ExecutionPlanner):
    """Supervisor sets route; Planner builds agent DAG subset (no new agents)."""

    def __init__(self):
        self._builder = StaticDependencyGraphBuilder()

    def plan(self, ctx: ExecutionContext) -> ExecutionPlan:
        full = self._builder.build()
        selected = self._select_agents(ctx)
        if not selected:
            skipped = [a for a in ALL_AGENT_IDS]
            return ExecutionPlan(
                graph=full,
                waves=[],
                skipped=skipped,
                reason="no_agents_for_route",
            )
        waves = waves_for_subset(selected, full)
        skipped = [a for a in ALL_AGENT_IDS if a not in selected]
        return ExecutionPlan(
            graph=full,
            waves=waves,
            skipped=skipped,
            reason=f"parallel:{','.join(selected)}",
        )

    def _select_agents(self, ctx: ExecutionContext) -> set[str]:
        route = (ctx.route or "").strip()
        msg = (ctx.message or "").strip()
        intent = (ctx.chip_intent or "").strip().lower()
        selected: set[str] = set()

        wants_success = intent in ("follow_up", "followup", "customer_success", "nurture") or bool(
            _SUCCESS_RE.search(msg)
        )
        wants_negotiation = intent in ("negotiate", "negotiation", "bargain", "discount") or bool(
            _NEGOTIATION_RE.search(msg)
        )
        wants_recommend = intent in ("recommend", "suggestion", "best") or bool(_RECOMMEND_RE.search(msg))
        wants_analysis = (
            route == ROUTE_PROPERTY_COMPARE
            or intent in ("analyze", "compare", "analysis")
            or bool(_ANALYSIS_RE.search(msg))
        )
        wants_memory = intent in ("profile", "customer_memory", "prefs") or bool(_MEMORY_RE.search(msg))
        wants_search = (
            route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE)
            or bool(_SEARCH_RE.search(msg))
            or wants_analysis
            or wants_recommend
            or wants_negotiation
        )

        # Build dependency chain as needed (include upstream).
        if wants_success:
            selected.update(
                {
                    AGENT_PROPERTY_SEARCH,
                    AGENT_PROPERTY_ANALYSIS,
                    AGENT_RECOMMENDATION,
                    AGENT_NEGOTIATION,
                    AGENT_FOLLOW_UP,
                    AGENT_CUSTOMER_MEMORY,
                }
            )
        elif wants_negotiation:
            selected.update(
                {
                    AGENT_PROPERTY_SEARCH,
                    AGENT_PROPERTY_ANALYSIS,
                    AGENT_RECOMMENDATION,
                    AGENT_NEGOTIATION,
                    AGENT_CUSTOMER_MEMORY,
                }
            )
        elif wants_recommend:
            selected.update(
                {
                    AGENT_PROPERTY_SEARCH,
                    AGENT_PROPERTY_ANALYSIS,
                    AGENT_RECOMMENDATION,
                    AGENT_CUSTOMER_MEMORY,
                }
            )
        elif wants_analysis:
            selected.update(
                {AGENT_PROPERTY_SEARCH, AGENT_PROPERTY_ANALYSIS, AGENT_CUSTOMER_MEMORY}
            )
        elif wants_search:
            selected.update({AGENT_PROPERTY_SEARCH, AGENT_CUSTOMER_MEMORY})
        elif wants_memory:
            selected.add(AGENT_CUSTOMER_MEMORY)

        # Greeting / empty → nothing
        if not msg and not route:
            return set()
        if msg in ("سلام", "درود", "hi", "hello") and not (
            wants_search or wants_analysis or wants_recommend or wants_negotiation or wants_success or wants_memory
        ):
            return set()

        return selected
