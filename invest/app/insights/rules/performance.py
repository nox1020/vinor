"""Performance, trade, and statistics insight rules."""

from __future__ import annotations

from app.analytics.models import AnalyticsBundle
from app.insights.categories import InsightCategory
from app.insights.models import Insight
from app.insights.rules._helpers import make_insight, pct
from app.insights.rules.base import InsightRule
from app.insights.severity import InsightSeverity


class NegativeRoiRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "negative_roi"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        roi = bundle.capital.roi_pct
        if roi >= 0 or bundle.capital.cash_invested <= 0:
            return []
        sev = InsightSeverity.CRITICAL if roi <= -20 else InsightSeverity.HIGH
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بازده منفی پورتفوی",
                description=f"ROI فعلی حدود {pct(roi)} است.",
                summary=f"ROI {pct(roi)}",
                category=InsightCategory.PERFORMANCE,
                severity=sev,
                priority=88,
                action="ترکیب دارایی و معاملات زیان‌ده را بازبینی کنید.",
                metrics={"roi_pct": roi},
            )
        ]


class PositiveRoiRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "positive_roi"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        roi = bundle.capital.roi_pct
        if roi < 10 or bundle.capital.cash_invested <= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بازده مثبت قابل‌توجه",
                description=f"ROI پورتفوی حدود {pct(roi)} است.",
                summary=f"ROI {pct(roi)}",
                category=InsightCategory.OPPORTUNITY,
                severity=InsightSeverity.LOW,
                priority=30,
                action="روند موفقیت را مستند کنید و از افزایش ناگهانی ریسک پرهیز کنید.",
                metrics={"roi_pct": roi},
            )
        ]


class LowWinRateRule(InsightRule):
    THRESHOLD = 40.0

    @property
    def rule_id(self) -> str:
        return "low_win_rate"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        if t.closed_trades < 5:
            return []
        if t.win_rate_pct >= self.THRESHOLD:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="نرخ موفقیت پایین",
                description=(
                    f"از {t.closed_trades} معامله بسته، نرخ برد {pct(t.win_rate_pct)} است."
                ),
                summary=f"Win rate {pct(t.win_rate_pct)}",
                category=InsightCategory.TRADE,
                severity=InsightSeverity.HIGH,
                priority=78,
                action="معیار ورود/خروج را سخت‌گیرانه‌تر کنید یا حجم هر معامله را کاهش دهید.",
                metrics={"win_rate_pct": t.win_rate_pct, "closed": t.closed_trades},
            )
        ]


class HighWinRateRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "high_win_rate"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        if t.closed_trades < 5 or t.win_rate_pct < 60:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="نرخ موفقیت بالا",
                description=f"نرخ برد معاملات بسته {pct(t.win_rate_pct)} است.",
                summary=f"Win rate {pct(t.win_rate_pct)}",
                category=InsightCategory.STATISTICS,
                severity=InsightSeverity.LOW,
                priority=25,
                action="الگوی معاملات سودده را حفظ کنید و از over-trading اجتناب کنید.",
                metrics={"win_rate_pct": t.win_rate_pct},
            )
        ]


class LowProfitFactorRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "low_profit_factor"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        if t.closed_trades < 5:
            return []
        pf = t.profit_factor
        if pf >= 1.0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="ضریب سود کمتر از یک",
                description=f"Profit Factor برابر {pf:.2f} است (سود ناخالص کمتر از زیان ناخالص).",
                summary=f"PF={pf:.2f}",
                category=InsightCategory.PERFORMANCE,
                severity=InsightSeverity.HIGH,
                priority=82,
                action="اندازه بردها را نسبت به ضررها بهبود دهید یا حد ضرر را زودتر اعمال کنید.",
                metrics={"profit_factor": pf},
            )
        ]


class NegativeExpectancyRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "negative_expectancy"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        if t.closed_trades < 5 or t.expectancy >= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="انتظار ریاضی منفی",
                description=(
                    f"Expectancy هر معامله بسته حدود {t.expectancy:,.0f} واحد منفی است."
                ),
                summary=f"Expectancy={t.expectancy:,.0f}",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.CRITICAL,
                priority=92,
                action="تا اصلاح فرآیند معامله، حجم را کم کنید.",
                metrics={"expectancy": t.expectancy},
            )
        ]


class WeakRecoveryFactorRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "weak_recovery_factor"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        if bundle.capital.net_profit <= 0:
            return []
        rf = t.recovery_factor
        if rf >= 1.0 or rf <= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بازیابی ضعیف نسبت به افت",
                description=(
                    f"Recovery Factor حدود {rf:.2f} است؛ سود خالص نسبت به drawdown کم است."
                ),
                summary=f"RF={rf:.2f}",
                category=InsightCategory.RISK,
                severity=InsightSeverity.MEDIUM,
                priority=58,
                action="کنترل افت و ثبات بازده را اولویت دهید.",
                metrics={"recovery_factor": rf},
            )
        ]


class HighFeeRatioRule(InsightRule):
    RATIO = 0.05

    @property
    def rule_id(self) -> str:
        return "high_fee_ratio"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        cap = bundle.capital
        base = max(abs(cap.net_profit), cap.cash_invested, 1.0)
        if cap.total_fees <= 0:
            return []
        ratio = cap.total_fees / base
        if ratio < self.RATIO:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="نسبت بالای کارمزد",
                description=(
                    f"کل کارمزدها {cap.total_fees:,.0f} واحد است "
                    f"(حدود {pct(ratio * 100)} نسبت به مبنای سرمایه/سود)."
                ),
                summary=f"Fees {cap.total_fees:,.0f}",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.MEDIUM,
                priority=65,
                action="تعداد معاملات کم‌حجم را کم کنید یا کارمزد پلتفرم را مقایسه کنید.",
                metrics={"total_fees": cap.total_fees, "fee_ratio": ratio},
            )
        ]


class FeeWarningRule(InsightRule):
    """Fees eat a large share of gross profit."""

    @property
    def rule_id(self) -> str:
        return "fee_warning"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        gp = bundle.capital.gross_profit
        fees = bundle.capital.total_fees
        if gp <= 0 or fees <= 0 or fees / gp < 0.25:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="کارمزد بخش بزرگی از سود ناخالص",
                description=(
                    f"کارمزد {pct(fees / gp * 100)} از سود ناخالص تحقق‌یافته را مصرف کرده است."
                ),
                summary="کارمزد بالا نسبت به سود",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.HIGH,
                priority=72,
                action="از معاملات با حاشیه سود کم که کارمزد را بی‌اثر می‌کند پرهیز کنید.",
                metrics={"fees": fees, "gross_profit": gp},
            )
        ]


class LargestWinnerRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "largest_winner"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        if t.closed_trades < 1 or t.largest_winner <= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بزرگ‌ترین معامله سودده",
                description=f"بیشترین سود یک معامله بسته حدود {t.largest_winner:,.0f} واحد بوده است.",
                summary=f"Max win {t.largest_winner:,.0f}",
                category=InsightCategory.STATISTICS,
                severity=InsightSeverity.LOW,
                priority=20,
                action="شرایط آن معامله را برای یادگیری ثبت کنید.",
                metrics={"largest_winner": t.largest_winner},
            )
        ]


class LargestLoserRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "largest_loser"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        t = bundle.trades
        if t.closed_trades < 1 or t.largest_loser >= 0:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="بزرگ‌ترین معامله زیان‌ده",
                description=f"بیشترین ضرر یک معامله حدود {t.largest_loser:,.0f} واحد بوده است.",
                summary=f"Max loss {t.largest_loser:,.0f}",
                category=InsightCategory.WARNING,
                severity=InsightSeverity.MEDIUM,
                priority=62,
                action="حد ضرر از پیش تعریف‌شده می‌تواند از تکرار چنین ضرری جلوگیری کند.",
                metrics={"largest_loser": t.largest_loser},
            )
        ]


class PortfolioGrowthRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "portfolio_growth"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        series = bundle.growth_series
        if len(series) < 2:
            return []
        first, last = series[0][1], series[-1][1]
        if first <= 0 or last <= first:
            return []
        growth = (last - first) / first * 100.0
        if growth < 5:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="رشد ارزش پورتفوی",
                description=(
                    f"از شروع سری رشد تا امروز ارزش حدود {pct(growth)} افزایش یافته است."
                ),
                summary=f"Growth {pct(growth)}",
                category=InsightCategory.PORTFOLIO,
                severity=InsightSeverity.LOW,
                priority=28,
                action="روند مثبت را با مدیریت ریسک حفظ کنید.",
                metrics={"growth_pct": growth, "start": first, "end": last},
            )
        ]


class PortfolioDeclineRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "portfolio_decline"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        series = bundle.growth_series
        if len(series) < 2:
            return []
        first, last = series[0][1], series[-1][1]
        if first <= 0 or last >= first:
            return []
        decline = (first - last) / first * 100.0
        if decline < 5:
            return []
        sev = InsightSeverity.CRITICAL if decline >= 25 else InsightSeverity.HIGH
        return [
            make_insight(
                rule_id=self.rule_id,
                title="کاهش ارزش پورتفوی",
                description=f"ارزش از ابتدای سری حدود {pct(decline)} کاهش یافته است.",
                summary=f"Decline {pct(decline)}",
                category=InsightCategory.PORTFOLIO,
                severity=sev,
                priority=86,
                action="بازبینی دارایی‌های زیان‌ده و توقف معاملات احساسی.",
                metrics={"decline_pct": decline},
            )
        ]


class HighUnrealizedLossRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "high_unrealized_loss"

    def evaluate(self, bundle: AnalyticsBundle) -> list[Insight]:
        u = bundle.capital.unrealized_pnl
        invested = bundle.capital.cash_invested
        if u >= 0 or invested <= 0:
            return []
        ratio = abs(u) / invested * 100.0
        if ratio < 10:
            return []
        return [
            make_insight(
                rule_id=self.rule_id,
                title="زیان تحقق‌نیافته قابل‌توجه",
                description=(
                    f"زیان تحقق‌نیافته {u:,.0f} واحد "
                    f"(حدود {pct(ratio)} هزینه سرمایه‌گذاری) است."
                ),
                summary=f"Unrealized {u:,.0f}",
                category=InsightCategory.RISK,
                severity=InsightSeverity.HIGH,
                priority=77,
                action="موقعیت‌های باز زیان‌ده را با برنامه مشخص مدیریت کنید.",
                metrics={"unrealized_pnl": u, "ratio_pct": ratio},
            )
        ]
