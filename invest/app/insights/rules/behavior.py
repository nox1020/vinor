"""Behavior and trading-activity insight rules."""

from __future__ import annotations

from app.analytics.models import AnalyticsBundle
from app.insights.categories import InsightCategory
from app.insights.models import Insight
from app.insights.rules._helpers import make_insight, pct
from app.insights.rules.base import InsightRule
from app.insights.severity import InsightSeverity


class TooManySmallTradesRule(InsightRule):
    """Average trade size is small relative to portfolio."""

    @property
    def rule_id(self) -> str:
        return "too_many_small_trades"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        cap = bundle.capital
        if t.total_trades < 8 or cap.portfolio_value <= 0:
            return []
        avg = cap.average_trade_size
        if avg <= 0:
            return []
        share = avg / cap.portfolio_value * 100.0
        if share >= 5:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="معاملات کوچک زیاد",
                description=(
                    f"میانگین اندازه معامله حدود {pct(share)} ارزش پورتفوی است "
                    f"({t.total_trades} معامله)."
                ),
                summary="معاملات خرد پرتکرار",
                category=InsightCategory.BEHAVIOR,
                severity=InsightSeverity.MEDIUM,
                priority=50,
                action="معاملات بسیار کوچک اغلب کارمزد را بالا می‌برند؛ حجم معنادارتری انتخاب کنید.",
                metrics={"avg_trade_size": avg, "share_pct": share},
            )
        ]


class OverTradingRule(InsightRule):
    """Many closed trades with low average holding days."""

    @property
    def rule_id(self) -> str:
        return "over_trading"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        cap = bundle.capital
        if t.closed_trades < 10:
            return []
        if cap.average_holding_days > 7:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="معاملات بیش از حد (Over-trading)",
                description=(
                    f"{t.closed_trades} معامله بسته با میانگین نگهداری "
                    f"{cap.average_holding_days:.1f} روز."
                ),
                summary="Over-trading",
                category=InsightCategory.BEHAVIOR,
                severity=InsightSeverity.HIGH,
                priority=74,
                action="تعداد معاملات را کاهش دهید و فقط با طرح مشخص وارد شوید.",
                metrics={
                    "closed_trades": t.closed_trades,
                    "avg_holding_days": cap.average_holding_days,
                },
            )
        ]


class UnderTradingRule(InsightRule):
    """Very few closed trades while portfolio has value."""

    @property
    def rule_id(self) -> str:
        return "under_trading"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        if bundle.capital.portfolio_value <= 0:
            return []
        if bundle.trades.closed_trades > 1:
            return []
        if bundle.trades.open_trades == 0 and bundle.trades.closed_trades == 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="فعالیت معاملاتی کم",
                description=(
                    f"فقط {bundle.trades.closed_trades} معامله بسته ثبت شده؛ "
                    f"{bundle.trades.open_trades} معامله باز دارید."
                ),
                summary="Under-trading / کم‌فعالیت",
                category=InsightCategory.BEHAVIOR,
                severity=InsightSeverity.LOW,
                priority=22,
                action="اگر هدف یادگیری فعال است، با حجم کم و برنامه مشخص تمرین کنید.",
                metrics={
                    "closed": bundle.trades.closed_trades,
                    "open": bundle.trades.open_trades,
                },
            )
        ]


class InactivePortfolioRule(InsightRule):
    """No trades and no value."""

    @property
    def rule_id(self) -> str:
        return "inactive_portfolio"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        if bundle.capital.portfolio_value > 0 or bundle.trades.total_trades > 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="پورتفوی غیرفعال",
                description="هنوز دارایی یا معامله‌ای ثبت نشده است.",
                summary="بدون داده",
                category=InsightCategory.PORTFOLIO,
                severity=InsightSeverity.LOW,
                priority=10,
                action="اولین دارایی یا معامله را ثبت کنید تا تحلیل فعال شود.",
                metrics={},
            )
        ]


class LongHoldingLossRule(InsightRule):
    """Assets with long average holding and negative return."""

    @property
    def rule_id(self) -> str:
        return "long_holding_loss"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        out: list[Insight] = []
        for a in bundle.assets:
            if a.average_holding_days < 60:
                continue
            if a.return_amount >= 0:
                continue
            out.append(
                make_insight(
                    rule_id=self.rule_id,
                    title="نگهداری طولانی با زیان",
                    description=(
                        f"«{a.name}» میانگین نگهداری {a.average_holding_days:.0f} روز "
                        f"و بازده {a.return_amount:,.0f} دارد."
                    ),
                    summary=f"{a.name}: نگهداری طولانی + زیان",
                    category=InsightCategory.BEHAVIOR,
                    severity=InsightSeverity.MEDIUM,
                    priority=68,
                    action="تصمیم بگیرید: برنامه خروج، یا دلیل بنیادی برای ادامه نگهداری.",
                    related_assets=[a.name],
                    metrics={
                        "holding_days": a.average_holding_days,
                        "return_amount": a.return_amount,
                    },
                    suffix=f":{a.asset_id}",
                )
            )
        return out[:3]


class ShortTermWinsRule(InsightRule):
    """Short average holding with strong win rate → short-term style works."""

    @property
    def rule_id(self) -> str:
        return "short_term_wins"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        cap = bundle.capital
        t = bundle.trades
        if t.closed_trades < 5:
            return []
        if cap.average_holding_days > 30 or t.win_rate_pct < 55:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="عملکرد بهتر در بازه کوتاه",
                description=(
                    f"میانگین نگهداری {cap.average_holding_days:.1f} روز و "
                    f"نرخ برد {pct(t.win_rate_pct)} است."
                ),
                summary="سبک کوتاه‌مدت موفق‌تر",
                category=InsightCategory.BEHAVIOR,
                severity=InsightSeverity.LOW,
                priority=35,
                action="استراتژی کوتاه‌مدت برای شما عملکرد بهتری داشته؛ آن را نظام‌مند کنید.",
                metrics={
                    "avg_holding_days": cap.average_holding_days,
                    "win_rate_pct": t.win_rate_pct,
                },
            )
        ]


class ConsecutiveLossMonthsRule(InsightRule):
    """Two or more consecutive losing months."""

    @property
    def rule_id(self) -> str:
        return "consecutive_loss_months"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        months = bundle.periods.get("monthly", [])
        if len(months) < 2:
            return []
        streak = 0
        max_streak = 0
        for m in months:
            if m.net_pnl < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        if max_streak < 2:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="ماه‌های زیان پشت‌سرهم",
                description=f"حداقل {max_streak} ماه پیاپی با سود خالص منفی در گزارش ماهانه.",
                summary=f"{max_streak} ماه زیان متوالی",
                category=InsightCategory.BEHAVIOR,
                severity=InsightSeverity.HIGH,
                priority=76,
                action="در دوره‌های زیان متوالی حجم را کم کنید و فرآیند را بازبینی کنید.",
                metrics={"max_streak": max_streak},
            )
        ]


class IdleCapitalRule(InsightRule):
    """
    Low current exposure vs cash invested — capital not deployed in open lots.

    (No separate cash ledger; uses exposure / invested as proxy.)
    """

    @property
    def rule_id(self) -> str:
        return "idle_capital"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        cap = bundle.capital
        if cap.cash_invested <= 0:
            return []
        if cap.current_exposure / cap.cash_invested >= 0.3:
            return []
        if bundle.trades.open_trades > 0 and cap.current_exposure > 0:
            return []
        if cap.portfolio_value <= 0 and bundle.trades.closed_trades > 0:
            return [
                make_insight(
                    rule_id=self.rule_id,
                    title="سرمایه بدون موقعیت باز",
                    description=(
                        "معاملات بسته دارید اما ارزش/قرارگیری باز نزدیک صفر است."
                    ),
                    summary="بدون exposure فعال",
                    category=InsightCategory.OPPORTUNITY,
                    severity=InsightSeverity.LOW,
                    priority=18,
                    action="اگر هدف سرمایه‌گذاری فعال است، برنامه ورود مجدد تعریف کنید.",
                    metrics={"exposure": cap.current_exposure},
                )
            ]
        return []
