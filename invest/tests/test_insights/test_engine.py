"""Engine, registry, and provider tests."""

from app.insights.engine import InvestmentInsightsEngine
from app.insights.registry import InsightRuleRegistry
from app.insights.rules import DEFAULT_RULES
from app.insights.rules.base import InsightRule
from app.insights.models import Insight
from app.insights.categories import InsightCategory
from app.insights.severity import InsightSeverity
from tests.test_insights.conftest_helpers import make_asset, make_bundle, make_capital


class _AlwaysFireRule(InsightRule):
    @property
    def rule_id(self) -> str:
        return "always_fire_test"

    def evaluate(self, bundle):
        from app.insights.rules._helpers import make_insight

        return [
            make_insight(
                rule_id=self.rule_id,
                title="t",
                description="d",
                summary="s",
                category=InsightCategory.STATISTICS,
                severity=InsightSeverity.LOW,
                action="a",
            )
        ]


def test_default_rules_count() -> None:
    assert len(DEFAULT_RULES) >= 30


def test_registry_plugin_register() -> None:
    reg = InsightRuleRegistry()
    reg.register(_AlwaysFireRule())
    assert "always_fire_test" in reg.rule_ids()
    engine = InvestmentInsightsEngine(reg)
    bundle = make_bundle(fingerprint="fp1")
    result = engine.generate(bundle)
    assert any(i.rule_id == "always_fire_test" for i in result.insights)


def test_engine_cache_by_fingerprint() -> None:
    engine = InvestmentInsightsEngine(InsightRuleRegistry.with_defaults())
    b1 = make_bundle(
        capital=make_capital(portfolio_value=100, cash_invested=100, roi_pct=-5),
        assets=[make_asset(name="X", allocation_pct=100, current_value=100)],
        fingerprint="same",
    )
    first = engine.generate(b1)
    second = engine.generate(b1)
    assert first is second  # same cached object
    b2 = make_bundle(fingerprint="other")
    third = engine.generate(b2)
    assert third.fingerprint == "other"


def test_engine_sorted_by_severity() -> None:
    engine = InvestmentInsightsEngine(InsightRuleRegistry.with_defaults())
    bundle = make_bundle(
        capital=make_capital(
            portfolio_value=100,
            cash_invested=100,
            roi_pct=-25,
            current_exposure=100,
        ),
        assets=[make_asset(name="Only", allocation_pct=100, current_value=100)],
        fingerprint="sev",
    )
    result = engine.generate(bundle)
    levels = [int(i.severity) for i in result.insights]
    assert levels == sorted(levels, reverse=True)
