from __future__ import annotations

import time
from typing import Any

from app.decision.interfaces import (
    ConflictResolver,
    DecisionConfig,
    ScoredCandidate,
)


class RuleConflictResolver(ConflictResolver):
    """Rule-based conflict resolution — keeps alternatives when uncertain."""

    def resolve(
        self,
        *,
        ranked: list[ScoredCandidate],
        shared: dict[str, Any],
        config: DecisionConfig,
    ) -> tuple[ScoredCandidate | None, list[ScoredCandidate], list[str], int]:
        t0 = time.perf_counter()
        conflicts: list[str] = []
        if not ranked:
            _ = int((time.perf_counter() - t0) * 1000)
            return None, [], [], 0

        winner = ranked[0]
        alts = list(ranked[1:4])

        if len(ranked) >= 2:
            gap = ranked[0].score - ranked[1].score
            if gap < config.conflict_margin:
                conflicts.append(f"close_scores:{ranked[0].property_code}/{ranked[1].property_code}")

        rec = str(shared.get("recommended_code") or "").strip()
        neg = shared.get("negotiation_plan") if isinstance(shared.get("negotiation_plan"), dict) else {}
        neg_code = str(neg.get("property_code") or "").strip()
        if rec and neg_code and rec != neg_code:
            conflicts.append(f"rec_vs_neg:{rec}/{neg_code}")
            # Prefer higher weighted blend already in scores; if negotiation deal_p high, bump neg code
            deal_p = float(neg.get("deal_probability") or 0)
            if deal_p >= 0.7:
                for c in ranked:
                    if c.property_code == neg_code:
                        winner = c
                        alts = [x for x in ranked if x.property_code != neg_code][:3]
                        conflicts.append("resolved:prefer_negotiation")
                        break
            else:
                conflicts.append("resolved:prefer_recommendation")

        # Analysis warning on winner → keep stronger alt if available
        if winner.warnings and alts and alts[0].score >= winner.score - config.conflict_margin:
            conflicts.append("resolved:keep_alternative_due_warning")

        # annotate resolve time on winner metadata via side channel not available — return count
        _resolve_ms = int((time.perf_counter() - t0) * 1000)
        winner.parts["_resolve_ms"] = float(_resolve_ms)
        return winner, alts, conflicts, len(conflicts)
