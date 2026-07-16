from __future__ import annotations

from collections import Counter
from typing import Any

from app.self_learning.interfaces import FailureDetector, LearningPattern, SuccessDetector


class RuleSuccessDetector(SuccessDetector):
    def detect(self, records: list[dict[str, Any]]) -> list[LearningPattern]:
        ok = [r for r in records if r.get("ok", True) and float((r.get("quality") or {}).get("overall") or r.get("decision_confidence") or 0) >= 0.6]
        agents = Counter(str(r.get("selected_agent") or "unknown") for r in ok)
        out: list[LearningPattern] = []
        for agent, cnt in agents.most_common(5):
            if cnt < 1:
                continue
            out.append(
                LearningPattern(
                    pattern_id=f"success_{agent}",
                    kind="success",
                    signal=f"agent_ok:{agent}",
                    weight=min(0.95, 0.4 + cnt * 0.05),
                    count=cnt,
                )
            )
        return out


class RuleFailureDetector(FailureDetector):
    def detect(self, records: list[dict[str, Any]]) -> list[LearningPattern]:
        bad = [r for r in records if (not r.get("ok", True)) or float((r.get("quality") or {}).get("conflict_rate") or 0) >= 0.3]
        intents = Counter(str(r.get("intent") or r.get("detected_intent") or "unknown") for r in bad)
        out: list[LearningPattern] = []
        for intent, cnt in intents.most_common(5):
            out.append(
                LearningPattern(
                    pattern_id=f"fail_{intent}",
                    kind="failure",
                    signal=f"intent_fail:{intent}",
                    weight=min(0.9, 0.35 + cnt * 0.08),
                    count=cnt,
                )
            )
        return out
