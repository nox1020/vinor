# Investment Insights Engine

Rule-based behavioral / risk / performance insights. **No AI, no price prediction, no UI logic.**

## Architecture

```
AnalyticsBundle  →  InvestmentInsightsEngine  →  InsightBundle
                           ↑
                    InsightRuleRegistry
                           ↑
                    InsightRule (plugins)
```

- Data source: only `AnalyticsBundle` from `PortfolioAnalyticsService`
- UI: `InsightProvider.list_insights()` → `InsightViewModel`
- Wire-up: `ctx.insights` / `ctx.insights_engine` (`AppContext`)

## Adding a rule (plugin)

```python
from app.insights.rules.base import InsightRule
from app.insights.rules._helpers import make_insight
# ...

class MyRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "my_rule"

    def evaluate(self, bundle):
        ...
        return [make_insight(...)]

# Register without changing engine:
ctx.insights_engine.registry.register(MyRule())
```

Or add to `DEFAULT_RULES` in `app/insights/rules/__init__.py`.

## Insight model

| Field | Meaning |
|-------|---------|
| id | Stable id (`rule_id` + optional suffix) |
| title / description / summary | User-facing text (Persian) |
| category | See `InsightCategory` |
| severity | LOW / MEDIUM / HIGH / CRITICAL |
| priority | Secondary sort (0–100) |
| action | Practical recommendation (not buy/sell advice) |
| related_assets / metrics | Context |

## Built-in rules (≥30)

| rule_id | Purpose | Typical severity |
|---------|---------|------------------|
| large_allocation | One asset >40% | HIGH/CRITICAL |
| single_asset_risk | Only one valued asset | CRITICAL |
| no_diversification | 2 valued assets | MEDIUM |
| holding_concentration | Top-2 ≥75% | HIGH |
| profit_concentration | ≥70% realized profit one asset | MEDIUM |
| loss_concentration | ≥60% losses one asset | HIGH |
| large_drawdown | MDD ≥15% of peak | HIGH/CRITICAL |
| high_exposure | Exposure/cost ≥1.2 | MEDIUM |
| negative_roi / positive_roi | ROI thresholds | … |
| low_win_rate / high_win_rate | Closed sample ≥5 | … |
| low_profit_factor | PF < 1 | HIGH |
| negative_expectancy | Expectancy < 0 | CRITICAL |
| weak_recovery_factor | RF in (0,1) | MEDIUM |
| high_fee_ratio / fee_warning | Fee burden | … |
| largest_winner / largest_loser | Extremes | … |
| portfolio_growth / portfolio_decline | Series endpoints | … |
| high_unrealized_loss | Unrealized vs cost | HIGH |
| too_many_small_trades | Tiny avg size | MEDIUM |
| over_trading / under_trading | Activity patterns | … |
| inactive_portfolio | Empty book | LOW |
| long_holding_loss | Long hold + loss | MEDIUM |
| short_term_wins | Short hold + high WR | LOW |
| consecutive_loss_months | ≥2 losing months | HIGH |
| idle_capital | No open exposure after closes | LOW |
| best_asset / worst_asset | Return extremes | … |
| popular_asset | Most trades | LOW |
| stagnant_asset | Flat return | LOW |
| losing_assets_count | Many losers | HIGH |
| best_month / worst_month | Period PnL | … |
| best_year / worst_year | Yearly | … |
| well_diversified | ≥4 assets, max <35% | LOW |
| goal_tracking_hint | Encourage defining goals | LOW |

## Caching

Engine caches `InsightBundle` by `AnalyticsBundle.fingerprint`. Call `ctx.insights.invalidate()` after data changes if needed (provider also clears analytics cache).

## Usage

```python
views = ctx.insights.list_insights(calendar=ctx.settings.calendar, limit=20)
for v in views:
    print(v.severity, v.title, "→", v.action)
```

## Tests

```bash
python -m pytest tests/test_insights -q
```
