from __future__ import annotations

import json
import os
import time
from typing import Any

from app.self_improvement.interfaces import ImprovementManager, ImprovementReport, ImprovementSuggestion


def self_improvement_enabled() -> bool:
    return (os.environ.get("VINOR_SELF_IMPROVEMENT_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _dir() -> str:
    try:
        from flask import current_app

        root = current_app.instance_path
    except Exception:
        root = os.path.join(os.getcwd(), "instance")
    path = os.path.join(root, "data", "self_improvement")
    os.makedirs(path, exist_ok=True)
    return path


class RuleImprovementManager(ImprovementManager):
    def improve(
        self,
        *,
        reflection: dict[str, Any] | None = None,
        learning: dict[str, Any] | None = None,
    ) -> ImprovementReport:
        t0 = time.perf_counter()
        reflection = reflection or {}
        learning = learning or {}
        suggestions: list[ImprovementSuggestion] = []
        if reflection.get("cost_high"):
            suggestions.append(
                ImprovementSuggestion(
                    area="cost",
                    title="کاهش بودجه Prompt",
                    recommendation="RAG/Memory budget را کاهش دهید (پیشنهاد — بدون اعمال خودکار).",
                    priority="high",
                    confidence=0.7,
                    source="reflection",
                )
            )
        if reflection.get("extra_tools"):
            suggestions.append(
                ImprovementSuggestion(
                    area="tools",
                    title="محدودسازی Tool rounds",
                    recommendation="سقف api_rounds را سخت‌گیرانه‌تر کنید.",
                    priority="medium",
                    confidence=0.65,
                    source="reflection",
                )
            )
        if not reflection.get("goal_completed", True):
            suggestions.append(
                ImprovementSuggestion(
                    area="goals",
                    title="تقویت مسیر Goal → Decision",
                    recommendation="Long Plan و Decision weights را برای goalهای ناقص بازبینی کنید.",
                    priority="high",
                    confidence=0.6,
                    source="reflection",
                )
            )
        for p in (learning.get("patterns") or [])[:8]:
            if not isinstance(p, dict):
                continue
            if p.get("kind") == "failure":
                suggestions.append(
                    ImprovementSuggestion(
                        area="learning",
                        title=f"الگوی شکست: {p.get('signal')}",
                        recommendation="قوانین routing/decision مربوط به این سیگنال را بازبینی کنید.",
                        priority="medium",
                        confidence=float(p.get("weight") or 0.5),
                        source="learning",
                    )
                )
        report = ImprovementReport(
            suggestions=suggestions[:20],
            applied=False,
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
        try:
            path = os.path.join(_dir(), f"report_{int(time.time())}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return report
