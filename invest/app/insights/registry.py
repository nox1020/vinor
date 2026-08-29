"""Plugin-style registry for insight rules."""

from __future__ import annotations

from app.insights.rules.base import InsightRule
from app.insights.rules import DEFAULT_RULES


class InsightRuleRegistry:
    """
    Register / unregister rules without modifying the engine core.

    New rules: ``registry.register(MyRule())``.
    """

    def __init__(self) -> None:
        self._rules: dict[str, InsightRule] = {}

    def register(self, rule: InsightRule) -> None:
        self._rules[rule.rule_id] = rule

    def unregister(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    def get(self, rule_id: str) -> InsightRule | None:
        return self._rules.get(rule_id)

    def all_rules(self) -> list[InsightRule]:
        return list(self._rules.values())

    def rule_ids(self) -> list[str]:
        return sorted(self._rules.keys())

    @classmethod
    def with_defaults(cls) -> InsightRuleRegistry:
        reg = cls()
        for rule in DEFAULT_RULES:
            reg.register(rule)
        return reg
