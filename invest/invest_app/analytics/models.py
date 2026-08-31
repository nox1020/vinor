"""Analytics result models (UI-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PortfolioCapitalMetrics:
    """Aggregate capital and PnL (toman base, same as DB)."""

    portfolio_value: float
    total_asset_value: float
    cash_invested: float
    current_exposure: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_pnl_pct: float
    roi_pct: float
    total_fees: float
    net_profit: float
    gross_profit: float
    gross_loss: float
    average_buy_price: float
    average_sell_price: float
    average_trade_size: float
    average_holding_days: float


@dataclass(frozen=True)
class TradeAnalytics:
    total_trades: int
    open_trades: int
    closed_trades: int
    average_profit: float
    average_loss: float
    max_profit: float
    max_loss: float
    win_rate_pct: float
    loss_rate_pct: float
    profit_factor: float
    average_winner: float
    average_loser: float
    largest_winner: float
    largest_loser: float
    expectancy: float
    recovery_factor: float


@dataclass(frozen=True)
class AssetAnalyticsRow:
    asset_id: int
    name: str
    symbol: str
    allocation_pct: float
    profit_share_pct: float
    return_amount: float
    return_pct: float
    invested: float
    current_value: float
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
    first_trade_date: str | None
    last_trade_date: str | None
    average_holding_days: float


@dataclass(frozen=True)
class PeriodPerformance:
    key: str
    profit: float
    loss: float
    net_pnl: float
    trade_count: int
    win_count: int
    success_rate_pct: float
    capital_growth_pct: float


@dataclass(frozen=True)
class ChartSeries:
    """Named series for charts: list of (label, value)."""

    name: str
    points: list[tuple[str, float]] = field(default_factory=list)


@dataclass(frozen=True)
class ChartBundle:
    capital_trend: ChartSeries
    profit_trend: ChartSeries
    allocation: ChartSeries
    capital_growth: ChartSeries
    monthly_profit: ChartSeries
    yearly_profit: ChartSeries
    by_asset_value: ChartSeries
    asset_comparison: ChartSeries


@dataclass(frozen=True)
class AnalyticsBundle:
    """Single computed snapshot; cache invalidates when fingerprint changes."""

    capital: PortfolioCapitalMetrics
    trades: TradeAnalytics
    assets: list[AssetAnalyticsRow]
    periods: dict[str, list[PeriodPerformance]]
    charts: ChartBundle
    growth_series: list[tuple[str, float]]
    fingerprint: str
    goal_roi_pct: float | None = None


@dataclass(frozen=True)
class PortfolioSummaryReport:
    capital: PortfolioCapitalMetrics
    trades: TradeAnalytics
    generated_at: str


@dataclass(frozen=True)
class AssetReport:
    rows: list[AssetAnalyticsRow]
    calendar: str


@dataclass(frozen=True)
class TradeReport:
    analytics: TradeAnalytics
    closed_count: int


@dataclass(frozen=True)
class PerformanceReport:
    periods: dict[str, list[PeriodPerformance]]
    growth_series: list[tuple[str, float]]
    calendar: str


@dataclass(frozen=True)
class TaxReportStub:
    """Placeholder for future tax reporting (no calculations yet)."""

    calendar: str
    note: str = "Tax rules not configured; export closed trades from Trade Report."
