from __future__ import annotations

from typing import Any

from app.self_learning.detectors import RuleFailureDetector, RuleSuccessDetector
from app.self_learning.interfaces import (
    FailureDetector,
    LearningPattern,
    PatternExtractor,
    SuccessDetector,
)


class RulePatternExtractor(PatternExtractor):
    def __init__(
        self,
        *,
        success: SuccessDetector | None = None,
        failure: FailureDetector | None = None,
    ):
        self._success = success or RuleSuccessDetector()
        self._failure = failure or RuleFailureDetector()

    def extract(self, records: list[dict[str, Any]]) -> list[LearningPattern]:
        patterns = []
        patterns.extend(self._success.detect(records or []))
        patterns.extend(self._failure.detect(records or []))
        # latency pattern
        lats = [float(r.get("latency_ms") or 0) for r in (records or [])]
        if lats:
            avg = sum(lats) / len(lats)
            if avg >= 2000:
                patterns.append(
                    LearningPattern(
                        pattern_id="latency_high",
                        kind="failure",
                        signal="latency_high",
                        weight=min(0.85, avg / 5000),
                        count=len(lats),
                        metadata={"avg_latency_ms": avg},
                    )
                )
        return patterns
