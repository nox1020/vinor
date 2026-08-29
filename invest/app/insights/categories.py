"""Insight categories for the Investment Insights Engine."""

from __future__ import annotations

from enum import Enum


class InsightCategory(str, Enum):
    """Classification of investment insights."""

    PORTFOLIO = "Portfolio"
    ASSET = "Asset"
    TRADE = "Trade"
    RISK = "Risk"
    PERFORMANCE = "Performance"
    BEHAVIOR = "Behavior"
    DIVERSIFICATION = "Diversification"
    OPPORTUNITY = "Opportunity"
    WARNING = "Warning"
    GOAL = "Goal"
    STATISTICS = "Statistics"
