"""Risk and diversification insight rules."""

from __future__ import annotations

from app.analytics.formulas import max_drawdown_from_series
from app.analytics.models import AnalyticsBundle
from app.insights.categories import InsightCategory
from app.insights.models import Insight
from app.insights.rules._helpers import make_insight, pct
from app.insights.rules.base import InsightRule
from app.insights.severity import InsightSeverity


class LargeAllocationRule(InsightRule):
    """Warn when a single asset exceeds allocation threshold."""

    THRESHOLD = 40.0

    @property
    def rule_id(self) -> str:
        return "large_allocation"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        if not bundle.assets:
            return []
        top = max(bundle.assets, key=lambda a: a.allocation_pct)
        if top.allocation_pct < self.THRESHOLD:
            return []
        sev = (
            InsightSeverity.CRITICAL
            if top.allocation_pct >= 70
            else InsightSeverity.HIGH
        )
        return [
            make_insight(
                rule_id=self.rule_id,
                title="تمرکز بالای سرمایه روی یک دارایی",
                description=(
                    f"{pct(top.allocation_pct)} از ارزش پورتفوی روی «{top.name}» "
                    f"متمرکز است."
                ),
                summary=f"تخصیص {pct(top.allocation_pct)} به {top.name}",
                category=InsightCategory.RISK,
                severity=sev,
                priority=90,
                action="برای کاهش ریسک تمرکز، تنوع دارایی‌ها را افزایش دهید.",
                related_assets=[top.name],
                metrics={"allocation_pct": top.allocation_pct, "asset": top.name},
            )
        ]


class SingleAssetRiskRule(InsightRule):
    """Portfolio consists of exactly one holding with value."""

    @property
    def rule_id(self) -> str:
        return "single_asset_risk"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        valued = [a for a in bundle.assets if a.current_value > 0]
        if len(valued) != 1:
            return []
        a = valued[0]
        return [
            make_insight(
                rule_id=self.rule_id,
                title="ریسک وابستگی به یک دارایی",
                description=(
                    f"کل ارزش پورتفوی فقط در «{a.name}» قرار دارد؛ "
                    "هیچ تنوعی وجود ندارد."
                ),
                summary=f"تنها دارایی فعال: {a.name}",
                category=InsightCategory.RISK,
                severity=InsightSeverity.CRITICAL,
                priority=95,
                action="افزودن دارایی‌های غیرهمبسته می‌تواند ریسک را کاهش دهد.",
                related_assets=[a.name],
                metrics={"asset_count": 1},
            )
        ]


class NoDiversificationRule(InsightRule):
    """Fewer than three valued assets."""

    @property
    def rule_id(self) -> str:
        return "no_diversification"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        valued = [a for a in bundle.assets if a.current_value > 0]
        if len(valued) == 0 or len(valued) >= 3:
            return []
        if len(valued) == 1:
            return []  # covered by SingleAssetRisk
        names = [a.name for a in valued]
        return [
            make_insight(
                rule_id=self.rule_id,
                title="تنوع کم در پورتفوی",
                description=f"فقط {len(valued)} دارایی با ارزش مثبت دارید: {', '.join(names)}.",
                summary=f"{len(valued)} دارایی فعال",
                category=InsightCategory.DIVERSIFICATION,
                severity=InsightSeverity.MEDIUM,
                priority=70,
                action="افزایش تعداد دارایی‌های مستقل به حداقل ۳ مورد توصیه می‌شود.",
                related_assets=names,
                metrics={"active_assets": len(valued)},
            )
        ]


class HoldingConcentrationRule(InsightRule):
    """Top two assets hold most of portfolio."""

    @property
    def rule_id(self) -> str:
        return "holding_concentration"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        valued = sorted(
            [a for a in bundle.assets if a.allocation_pct > 0],
            key=lambda a: a.allocation_pct,
            reverse=True,
        )
        if len(valued) < 2:
            return []
        top2 = valued[0].allocation_pct + valued[1].allocation_pct
        if top2 < 75:
            return []
        names = [valued[0].name, valued[1].name]
        return [
            make_insight(
                rule_id=self.rule_id,
                title="تمرکز نگهداری در دو دارایی",
                description=(
                    f"{pct(top2)} سرمایه در «{names[0]}» و «{names[1]}» متمرکز است."
                ),
                summary=f"دو دارایی: {pct(top2)}",
                category=InsightCategory.DIVERSIFICATION,
                severity=InsightSeverity.HIGH,
                priority=80,
                action="بازبینی وزن‌ها و افزودن دارایی سوم برای کاهش تمرکز.",
                related_assets=names,
                metrics={"top2_allocation_pct": top2},
            )
        ]


class ProfitConcentrationRule(InsightRule):
    """Most realized profit from one asset."""

    @property
    def rule_id(self) -> str:
        return "profit_concentration"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        total = bundle.capital.realized_pnl
        if total <= 0:
            return []
        best = max(bundle.assets, key=lambda a: a.realized_pnl, default=None)
        if best is None or best.profit_share_pct < 70:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="تمرکز سود روی یک دارایی",
                description=(
                    f"{pct(best.profit_share_pct)} سود تحقق‌یافته از «{best.name}» آمده است."
                ),
                summary=f"سود متمرکز: {best.name}",
                category=InsightCategory.PERFORMANCE,
                severity=InsightSeverity.MEDIUM,
                priority=60,
                action="عملکرد خوب است؛ مراقب وابستگی سود به یک دارایی باشید.",
                related_assets=[best.name],
                metrics={"profit_share_pct": best.profit_share_pct},
            )
        ]


class LargeDrawdownRule(InsightRule):
    """Significant peak-to-trough drop on growth series."""

    RATIO = 0.15

    @property
    def rule_id(self) -> str:
        return "large_drawdown"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        values = [v for _, v in bundle.growth_series]
        if len(values) < 2:
            return []
        mdd = max_drawdown_from_series(values)
        peak = max(values) if values else 0.0
        if peak <= 0 or mdd / peak < self.RATIO:
            return []
        ratio_pct = (mdd / peak) * 100.0
        sev = (
            InsightSeverity.CRITICAL
            if ratio_pct >= 30
            else InsightSeverity.HIGH
        )
        return [
            make_insight(
                rule_id=self.rule_id,
                title="افت قابل‌توجه سرمایه",
                description=(
                    f"بیشترین افت از قله تا کف حدود {pct(ratio_pct)} "
                    f"(معادل {mdd:,.0f} واحد) بوده است."
                ),
                summary=f"Drawdown ≈ {pct(ratio_pct)}",
                category=InsightCategory.RISK,
                severity=sev,
                priority=85,
                action="حد ضرر و تنوع را بازبینی کنید؛ از افزایش حجم در افت‌های عمیق پرهیز کنید.",
                metrics={"max_drawdown": mdd, "drawdown_pct": ratio_pct},
            )
        ]


class HighExposureRule(InsightRule):
    """Open exposure close to or above invested cost."""

    @property
    def rule_id(self) -> str:
        return "high_exposure"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        cap = bundle.capital
        if cap.cash_invested <= 0 or cap.current_exposure <= 0:
            return []
        ratio = cap.current_exposure / cap.cash_invested
        if ratio < 1.2:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="قرارگیری بالای بازار (Exposure)",
                description=(
                    f"ارزش موقعیت‌های باز {pct(ratio * 100, 0)} نسبت به هزینه "
                    f"سرمایه‌گذاری است."
                ),
                summary=f"Exposure/Cost ≈ {ratio:.2f}x",
                category=InsightCategory.RISK,
                severity=InsightSeverity.MEDIUM,
                priority=55,
                action="سطح موقعیت‌های باز را با تحمل ریسک خود هم‌راستا کنید.",
                metrics={
                    "exposure": cap.current_exposure,
                    "invested": cap.cash_invested,
                    "ratio": ratio,
                },
            )
        ]


class LossConcentrationRule(InsightRule):
    """Largest share of losses from one asset."""

    @property
    def rule_id(self) -> str:
        return "loss_concentration"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        losers = [a for a in bundle.assets if a.realized_pnl < 0]
        if not losers:
            return []
        total_loss = abs(sum(a.realized_pnl for a in losers))
        if total_loss <= 0:
            return []
        worst = min(losers, key=lambda a: a.realized_pnl)
        share = abs(worst.realized_pnl) / total_loss * 100.0
        if share < 60:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="تمرکز ضرر روی یک دارایی",
                description=(
                    f"{pct(share)} ضررهای تحقق‌یافته مربوط به «{worst.name}» است."
                ),
                summary=f"ضرر متمرکز: {worst.name}",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.HIGH,
                priority=75,
                action="دلایل زیان این دارایی را بررسی کنید و حد ضرر مشخص کنید.",
                related_assets=[worst.name],
                metrics={"loss_share_pct": share, "realized_pnl": worst.realized_pnl},
            )
        ]
