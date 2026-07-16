from __future__ import annotations

import json
import os
import time
from typing import Any

from app.self_learning.extractor import RulePatternExtractor
from app.self_learning.interfaces import LearningManager, LearningReport, PatternExtractor


def _store_dir() -> str:
    try:
        from flask import current_app

        root = current_app.instance_path
    except Exception:
        root = os.path.join(os.getcwd(), "instance")
    path = os.path.join(root, "data", "self_learning")
    os.makedirs(path, exist_ok=True)
    return path


class DefaultLearningManager(LearningManager):
    def __init__(self, *, extractor: PatternExtractor | None = None):
        self._extractor = extractor or RulePatternExtractor()

    def learn(self, records: list[dict[str, Any]] | None = None) -> LearningReport:
        t0 = time.perf_counter()
        records = list(records or [])
        if not records:
            try:
                from app.evaluation.storage import read_evaluation_records

                since = int(time.time()) - 7 * 86400
                records = read_evaluation_records(since_ts=since, limit=2000)
            except Exception:
                records = []
        patterns = self._extractor.extract(records)
        report = LearningReport(
            patterns=patterns[:50],
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
        try:
            path = os.path.join(_store_dir(), f"patterns_{int(time.time())}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            latest = os.path.join(_store_dir(), "latest.json")
            with open(latest, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return report
