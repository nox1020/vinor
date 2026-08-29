"""Asset- and period-focused opportunity / statistics rules."""

from __future__ import annotations

from app.analytics.models import AnalyticsBundle
from app.insights.categories import InsightCategory
from app.insights.models import Insight
from app.insights.rules._helpers import make_insight, pct
from app.insights.rules.base import InsightRule
from app.insights.severity import InsightSeverity


class BestAssetRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "best_asset"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        if not bundle.assets:
            return []
        best = max(bundle.assets, key=lambda a: a.return_amount)
        if best.return_amount <= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بهترین دارایی از نظر بازده",
                description=(
                    f"«{best.name}» با بازده {best.return_amount:,.0f} "
                    f"({pct(best.return_pct)}) بهترین عملکرد را داشته است."
                ),
                summary=f"Best: {best.name}",
                category=InsightCategory.OPPORTUNITY,
                severity=InsightSeverity.LOW,
                priority=32,
                action="نقاط قوت این دارایی را برای یادگیری نگه دارید؛ از تمرکز بیش از حد بپرهیزید.",
                related_assets=[best.name],
                metrics={
                    "return_amount": best.return_amount,
                    "return_pct": best.return_pct,
                },
            )
        ]


class WorstAssetRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "worst_asset"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        if not bundle.assets:
            return []
        worst = min(bundle.assets, key=lambda a: a.return_amount)
        if worst.return_amount >= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="ضعیف‌ترین دارایی از نظر بازده",
                description=(
                    f"«{worst.name}» با بازده {worst.return_amount:,.0f} "
                    f"({pct(worst.return_pct)}) ضعیف‌ترین عملکرد را دارد."
                ),
                summary=f"Worst: {worst.name}",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.MEDIUM,
                priority=64,
                action="دلیل زیان را بررسی کنید و برای نگهداری یا خروج تصمیم روشن بگیرید.",
                related_assets=[worst.name],
                metrics={
                    "return_amount": worst.return_amount,
                    "return_pct": worst.return_pct,
                },
            )
        ]


class PopularAssetRule(InsightRule):
    """Asset with most trades."""

    @property
    def rule_id(self) -> str:
        return "popular_asset"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        if not bundle.assets:
            return []
        top = max(bundle.assets, key=lambda a: a.trade_count)
        if top.trade_count < 3:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="دارایی پرمعامله (محبوب)",
                description=(
                    f"«{top.name}» با {top.trade_count} معامله بیشترین فعالیت را داشته است."
                ),
                summary=f"محبوب: {top.name}",
                category=InsightCategory.BEHAVIOR,
                severity=InsightSeverity.LOW,
                priority=24,
                action="اطمینان حاصل کنید علاقه احساسی جایگزین تحلیل نشده باشد.",
                related_assets=[top.name],
                metrics={"trade_count": top.trade_count},
            )
        ]


class StagnantAssetRule(InsightRule):
    """Assets with value but near-zero return."""

    @property
    def rule_id(self) -> str:
        return "stagnant_asset"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        out: list[Insight] = []
        for a in bundle.assets:
            if a.current_value <= 0 or a.invested <= 0:
                continue
            if abs(a.return_pct) > 2:
                continue
            out.append(
                make_insight(
                    rule_id=self.rule_id,
                    title="دارایی بدون رشد محسوس",
                    description=(
                        f"«{a.name}» بازده حدود {pct(a.return_pct)} دارد "
                        f"(ارزش {a.current_value:,.0f})."
                    ),
                    summary=f"راکد: {a.name}",
                    category=InsightCategory.ASSET,
                    severity=InsightSeverity.LOW,
                    priority=26,
                    action="هدف نگهداری را مشخص کنید یا سرمایه را به فرصت بهتر منتقل کنید.",
                    related_assets=[a.name],
                    metrics={"return_pct": a.return_pct},
                    suffix=f":{a.asset_id}",
                )
            )
        return out[:3]


class LosingAssetsCountRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "losing_assets_count"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        losers = [a for a in bundle.assets if a.return_amount < 0]
        total = len([a for a in bundle.assets if a.current_value > 0 or a.trade_count > 0])
        if len(losers) < 2 or total < 3:
            return []
        share = len(losers) / total * 100.0
        if share < 50:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بخش بزرگی از دارایی‌ها زیان‌ده",
                description=(
                    f"{len(losers)} از {total} دارایی ({pct(share)}) بازده منفی دارند."
                ),
                summary=f"{len(losers)}/{total} زیان‌ده",
                category=InsightCategory.RISK,
                severity=InsightSeverity.HIGH,
                priority=79,
                action="لیست زیان‌ده‌ها را اولویت‌بندی و برای هرکدام تصمیم بگیرید.",
                related_assets=[a.name for a in losers[:5]],
                metrics={"losing": len(losers), "total": total},
            )
        ]


class BestMonthRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "best_month"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        months = bundle.periods.get("monthly", [])
        if not months:
            return []
        best = max(months, key=lambda p: p.net_pnl)
        if best.net_pnl <= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بهترین ماه معاملاتی",
                description=(
                    f"ماه «{best.key}» با سود خالص {best.net_pnl:,.0f} "
                    f"و {best.trade_count} معامله بهترین بوده است."
                ),
                summary=f"Best month {best.key}",
                category=InsightCategory.OPPORTUNITY,
                severity=InsightSeverity.LOW,
                priority=27,
                action="شرایط آن ماه را برای تکرار آگاهانه بررسی کنید.",
                metrics={"key": best.key, "net_pnl": best.net_pnl},
            )
        ]


class WorstMonthRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "worst_month"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        months = bundle.periods.get("monthly", [])
        if not months:
            return []
        worst = min(months, key=lambda p: p.net_pnl)
        if worst.net_pnl >= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="ضعیف‌ترین ماه معاملاتی",
                description=(
                    f"ماه «{worst.key}» با سود خالص {worst.net_pnl:,.0f} "
                    f"ضعیف‌ترین بوده است."
                ),
                summary=f"Worst month {worst.key}",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.MEDIUM,
                priority=61,
                action="از تکرار اشتباهات آن ماه (حجم، زمان‌بندی، دارایی) پرهیز کنید.",
                metrics={"key": worst.key, "net_pnl": worst.net_pnl},
            )
        ]


class BestYearRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "best_year"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        years = bundle.periods.get("yearly", [])
        if not years:
            return []
        best = max(years, key=lambda p: p.net_pnl)
        if best.net_pnl <= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بهترین سال",
                description=f"سال «{best.key}» با سود خالص {best.net_pnl:,.0f} بهترین بوده است.",
                summary=f"Best year {best.key}",
                category=InsightCategory.STATISTICS,
                severity=InsightSeverity.LOW,
                priority=21,
                action="عوامل موفقیت آن سال را مستند کنید.",
                metrics={"key": best.key, "net_pnl": best.net_pnl},
            )
        ]


class WorstYearRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "worst_year"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        years = bundle.periods.get("yearly", [])
        if not years:
            return []
        worst = min(years, key=lambda p: p.net_pnl)
        if worst.net_pnl >= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="ضعیف‌ترین سال",
                description=f"سال «{worst.key}» با سود خالص {worst.net_pnl:,.0f} ضعیف‌ترین بوده است.",
                summary=f"Worst year {worst.key}",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.MEDIUM,
                priority=59,
                action="درس‌های آن سال را در قوانین معاملاتی خود اعمال کنید.",
                metrics={"key": worst.key, "net_pnl": worst.net_pnl},
            )
        ]


class WellDiversifiedRule(InsightRule):
    """Positive note when allocation is spread."""

    @property
    def rule_id(self) -> str:
        return "well_diversified"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        valued = [a for a in bundle.assets if a.allocation_pct > 0]
        if len(valued) < 4:
            return []
        top = max(a.allocation_pct for a in valued)
        if top > 35:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="تنوع مناسب پورتفوی",
                description=(
                    f"{len(valued)} دارایی فعال دارید و هیچ‌کدام بیش از "
                    f"{pct(top)} وزن ندارد."
                ),
                summary="Diversified",
                category=InsightCategory.DIVERSIFICATION,
                severity=InsightSeverity.LOW,
                priority=15,
                action="تنوع فعلی را حفظ کنید و همبستگی دارایی‌ها را گاه‌به‌گاه چک کنید.",
                metrics={"asset_count": len(valued), "max_allocation_pct": top},
            )
        ]


class GoalTrackingStubRule(InsightRule):
    """Encourage defining a goal when none is set."""

    @property
    def rule_id(self) -> str:
        return "goal_tracking_hint"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        if bundle.goal_roi_pct is not None:
            return []
        if bundle.capital.cash_invested <= 0:
            return []
        if bundle.trades.total_trades < 1:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="تعریف هدف سرمایه‌گذاری",
                description=(
                    "هنوز هدف بازده در تنظیمات تعریف نشده؛ با ROI فعلی "
                    f"{pct(bundle.capital.roi_pct)} می‌توانید هدف سالانه بگذارید."
                ),
                summary="پیشنهاد تعریف هدف",
                category=InsightCategory.GOAL,
                severity=InsightSeverity.LOW,
                priority=12,
                action="در تنظیمات، هدف بازده سالانه (٪) را وارد کنید.",
                metrics={"roi_pct": bundle.capital.roi_pct},
            )
        ]


class GoalProgressRule(InsightRule):
    """Compare portfolio ROI against user goal."""

    @property
    def rule_id(self) -> str:
        return "goal_progress"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        goal = bundle.goal_roi_pct
        if goal is None:
            return []
        roi = bundle.capital.roi_pct
        gap = roi - goal
        if gap >= 0:
            return [
                make_insight(
                    rule_id=self.rule_id,
                    title="هدف بازده محقق شده",
                    description=(
                        f"ROI فعلی {pct(roi)} از هدف {pct(goal)} بالاتر یا برابر است."
                    ),
                    summary=f"هدف {pct(goal)} ✓",
                    category=InsightCategory.GOAL,
                    severity=InsightSeverity.LOW,
                    priority=40,
                    action="هدف را کمی بالاتر ببرید یا تنوع را حفظ کنید.",
                    metrics={"roi_pct": roi, "goal_roi_pct": goal, "gap": gap},
                )
            ]
        sev = InsightSeverity.HIGH if gap <= -10 else InsightSeverity.MEDIUM
        return [
            make_insight(
                rule_id=self.rule_id,
                title="فاصله تا هدف بازده",
                description=(
                    f"ROI فعلی {pct(roi)} است؛ تا هدف {pct(goal)} حدود "
                    f"{pct(abs(gap))} فاصله دارید."
                ),
                summary=f"هدف {pct(goal)} — فاصله {pct(abs(gap))}",
                category=InsightCategory.GOAL,
                severity=sev,
                priority=70,
                action="بازبینی دارایی‌های زیان‌ده و هزینه‌ها می‌تواند فاصله تا هدف را کم کند.",
                metrics={"roi_pct": roi, "goal_roi_pct": goal, "gap": gap},
            )
        ]
