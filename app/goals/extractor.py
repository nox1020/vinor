from __future__ import annotations

import re
import uuid

from app.goals.interfaces import Goal, GoalContext, GoalExtractor, GoalPriority, GoalStatus, GoalType


class RuleGoalExtractor(GoalExtractor):
    def extract(self, ctx: GoalContext) -> list[Goal]:
        text = (ctx.message or "").strip()
        intent = (ctx.intent or ctx.route or "").lower()
        goals: list[Goal] = []

        def add(gtype: str, title: str, priority: str, conf: float) -> None:
            goals.append(
                Goal(
                    goal_id=uuid.uuid4().hex[:12],
                    goal_type=gtype,
                    title=title,
                    priority=priority,
                    status=GoalStatus.ACTIVE.value,
                    confidence=conf,
                    metadata={"intent": intent, "audience": ctx.audience},
                )
            )

        if any(k in text for k in ("بخر", "خرید", "می‌خوام بخرم", "میخوام بخرم")) or "buy" in intent:
            add(GoalType.BUY.value, "خرید ملک", GoalPriority.HIGH.value, 0.75)
        if any(k in text for k in ("بفروش", "فروش", "آگهی بذار")) or "sell" in intent:
            add(GoalType.SELL.value, "فروش ملک", GoalPriority.HIGH.value, 0.7)
        if any(k in text for k in ("بازدید", "نشون بده", "ببینم")) or "visit" in intent:
            add(GoalType.VISIT.value, "بازدید ملک", GoalPriority.MEDIUM.value, 0.65)
        if any(k in text for k in ("قیمت", "تخفیف", "چانه", "مذاکره")) or "negotiat" in intent:
            add(GoalType.NEGOTIATE.value, "مذاکره قیمت", GoalPriority.MEDIUM.value, 0.6)
        if any(k in text for k in ("همکار", "نماینده", "پورسانت")) or "partner" in intent:
            add(GoalType.PARTNER.value, "همکاری", GoalPriority.MEDIUM.value, 0.55)
        if any(k in text for k in ("ویلا", "زمین", "ملک", "آگهی", "جستجو", "پیدا")) or "search" in intent or "property" in intent:
            add(GoalType.SEARCH.value, "جستجوی ملک", GoalPriority.HIGH.value, 0.7)
        if any(k in text for k in ("پشتیبانی", "مشکل", "کمک")) or "support" in intent:
            add(GoalType.SUPPORT.value, "پشتیبانی", GoalPriority.MEDIUM.value, 0.55)

        if not goals and text:
            # greeting / general
            if re.search(r"سلام|خوبی|صبح|عصر", text):
                add(GoalType.GENERAL.value, "گفتگوی عمومی", GoalPriority.LOW.value, 0.4)
            else:
                add(GoalType.GENERAL.value, "هدف عمومی", GoalPriority.LOW.value, 0.35)
        return goals
