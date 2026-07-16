from __future__ import annotations

import re
import uuid

from app.planning.interfaces import (
    PLAN_FOLLOW_UP,
    PLAN_INFORMATION,
    PLAN_PROPERTY_COMPARE,
    PLAN_PROPERTY_RECOMMENDATION,
    PLAN_PROPERTY_SEARCH,
    Plan,
    Planner,
    PlanningRequest,
    Task,
)

_COMPARE_RE = re.compile(r"(مقایسه|بین این|کدام بهتر|فرق)", re.I)
_REC_RE = re.compile(r"(پیشنهاد|مناسب|بهترین|پیشنهاد بده|توصیه)", re.I)
_SEARCH_RE = re.compile(
    r"(ویلا|زمین|باغ|ملک|فایل|پیدا|جستجو|گرمابسرد|دماوند|بودجه|میلیارد)",
    re.I,
)
_INFO_RE = re.compile(r"(همکاری|پورسانت|شرایط|وضعیت درخواست|سطوح)", re.I)
_FOLLOW_RE = re.compile(r"(بعدی|کار بعدی|چی کار کنم|مرحله بعد)", re.I)


class RulePlanner(Planner):
    """Rule-based planner — structured Plan object only, no LLM tokens."""

    def create_plan(self, req: PlanningRequest) -> Plan:
        goal = (req.goal or "").strip()
        intent = (req.chip_intent or "").strip().lower()
        plan_type = _detect_plan_type(goal, intent)
        tasks = _tasks_for_plan(plan_type, goal, intent)
        return Plan(
            id=str(uuid.uuid4()),
            plan_type=plan_type,
            goal=goal,
            tasks=tasks,
            metadata={"chip_intent": intent, "audience": req.audience, "voice": req.voice},
        )


def _detect_plan_type(goal: str, intent: str) -> str:
    if intent in ("find_land",):
        return PLAN_PROPERTY_SEARCH
    if intent in ("next_action",):
        return PLAN_FOLLOW_UP
    if intent in ("coop_levels", "coop_terms", "coop_how", "coop_status", "coop_apply"):
        return PLAN_INFORMATION
    if intent in ("marketing",):
        return PLAN_FOLLOW_UP
    g = goal or ""
    if _COMPARE_RE.search(g):
        return PLAN_PROPERTY_COMPARE
    if _REC_RE.search(g) and _SEARCH_RE.search(g):
        return PLAN_PROPERTY_RECOMMENDATION
    if _FOLLOW_RE.search(g):
        return PLAN_FOLLOW_UP
    if _INFO_RE.search(g):
        return PLAN_INFORMATION
    if _SEARCH_RE.search(g):
        return PLAN_PROPERTY_SEARCH
    if _REC_RE.search(g):
        return PLAN_PROPERTY_RECOMMENDATION
    return PLAN_FOLLOW_UP


def _tasks_for_plan(plan_type: str, goal: str, intent: str) -> list[Task]:
    if plan_type == PLAN_PROPERTY_SEARCH:
        return [
            Task(id="t1", name="analyze_need"),
            Task(id="t2", name="search", tool_name="search_lands", tool_args={"query": goal, "limit": 5}),
            Task(id="t3", name="rank_results"),
            Task(id="t4", name="select_best"),
            Task(id="t5", name="compose_response"),
        ]
    if plan_type == PLAN_PROPERTY_COMPARE:
        return [
            Task(id="t1", name="analyze_compare_need"),
            Task(id="t2", name="search", tool_name="search_lands", tool_args={"query": goal, "limit": 5}),
            Task(id="t3", name="compare_candidates"),
            Task(id="t4", name="compose_response"),
        ]
    if plan_type == PLAN_PROPERTY_RECOMMENDATION:
        return [
            Task(id="t1", name="analyze_preferences"),
            Task(id="t2", name="search", tool_name="search_lands", tool_args={"query": goal, "limit": 5}),
            Task(id="t3", name="recommend"),
            Task(id="t4", name="compose_response"),
        ]
    if plan_type == PLAN_INFORMATION:
        topic = "all"
        if intent == "coop_levels":
            topic = "levels"
        elif intent == "coop_terms":
            topic = "terms"
        elif intent == "coop_how":
            topic = "how"
        if intent == "coop_status":
            return [
                Task(id="t1", name="check_status", tool_name="get_application_status", tool_args={}),
                Task(id="t2", name="compose_response"),
            ]
        return [
            Task(id="t1", name="fetch_info", tool_name="get_cooperation_info", tool_args={"topic": topic}),
            Task(id="t2", name="compose_response"),
        ]
    # follow_up default
    if intent == "marketing":
        return [
            Task(id="t1", name="draft_listing", tool_name="draft_listing_copy", tool_args={}),
            Task(id="t2", name="compose_response"),
        ]
    return [
        Task(id="t1", name="suggest_next", tool_name="suggest_next_action", tool_args={}),
        Task(id="t2", name="compose_response"),
    ]
