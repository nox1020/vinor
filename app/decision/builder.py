from __future__ import annotations

from typing import Any

from app.decision.interfaces import (
    DecisionBuilder,
    DecisionConfig,
    DecisionResult,
    ScoredCandidate,
)


class RuleDecisionBuilder(DecisionBuilder):
    """Builds Final Decision Object + compact hint — no dialogue / no prompt body."""

    def build(
        self,
        *,
        winner: ScoredCandidate | None,
        alternatives: list[ScoredCandidate],
        conflicts: list[str],
        shared: dict[str, Any],
        config: DecisionConfig,
    ) -> DecisionResult:
        if winner is None:
            return DecisionResult(
                next_step="gather_more",
                confidence=0.2,
                reasons=["no_candidates"],
                warnings=["empty_shared"],
                compact_hint="",
                decision_tokens=0,
                conflict_count=len(conflicts),
                conflicts=list(conflicts),
            )

        success = shared.get("customer_success") if isinstance(shared.get("customer_success"), dict) else {}
        neg = shared.get("negotiation_plan") if isinstance(shared.get("negotiation_plan"), dict) else {}

        next_step = str(
            success.get("next_action")
            or neg.get("next_action")
            or "continue_chat"
        )
        actions: list[str] = []
        if success.get("followup_type"):
            actions.append(str(success.get("followup_type")))
        if neg.get("recommended_strategy"):
            actions.append(str(neg.get("recommended_strategy")))
        if not actions:
            actions.append("review_selection")

        reasons = list(winner.reasons)
        if winner.score >= 0.7:
            reasons.append("high_decision_score")
        warnings = list(winner.warnings)
        if conflicts:
            warnings.append("had_conflicts")

        confidence = min(
            0.95,
            0.35
            + winner.score * 0.45
            + (0.1 if not conflicts else 0.0)
            + (0.05 if alternatives else 0.0)
            + (0.05 if shared.get("parallel_merge") else 0.0),
        )

        hint = self._compact_hint(
            code=winner.property_code,
            score=winner.score,
            next_step=next_step,
            budget=int(config.hint_budget_chars or 60),
        )
        return DecisionResult(
            selected_property=winner.property_code,
            alternative_properties=[a.property_code for a in alternatives],
            decision_score=round(winner.score, 4),
            confidence=round(confidence, 3),
            reasons=reasons[:8],
            warnings=warnings[:6],
            recommended_actions=actions[:4],
            next_step=next_step,
            conflict_count=len(conflicts),
            conflicts=list(conflicts)[:6],
            compact_hint=hint,
            decision_tokens=(len(hint) + 3) // 4 if hint else 0,
            conflict_resolve_time_ms=int(winner.parts.get("_resolve_ms") or 0),
            metadata={"parts": dict(winner.parts)},
        )

    def _compact_hint(self, *, code: str, score: float, next_step: str, budget: int) -> str:
        budget = max(40, min(budget or 60, 70))
        header = "=== تصمیم === "
        short_code = (code or "-")[-8:]
        body = f"{short_code}|{score:.2f}|{next_step[:10]}"
        room = budget - len(header)
        if len(body) > room:
            body = body[: max(0, room - 1)] + "…"
        return (header + body)[:budget]
