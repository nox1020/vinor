from __future__ import annotations

from typing import Any

from app.evaluation.interfaces import LayerMetrics, QualityEvaluator, QualityScores


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class RuleQualityEvaluator(QualityEvaluator):
    """Rule-based quality — no LLM / no re-scoring of agents."""

    def evaluate(self, *, row: dict[str, Any], layers: LayerMetrics) -> QualityScores:
        row = row or {}
        notes: list[str] = []

        ok = bool(row.get("ok", True))
        retries = int(row.get("retry_count") or layers.adaptive.get("retry_count") or 0)
        conflicts = int(layers.decision.get("conflict_count") or row.get("conflict_count") or 0)
        d_score = float(layers.decision.get("decision_score") or row.get("decision_score") or 0)
        d_conf = float(
            layers.decision.get("decision_confidence") or row.get("decision_confidence") or 0
        )
        selected = str(
            layers.decision.get("selected_property")
            or row.get("decision_selected_property")
            or row.get("selected_property")
            or ""
        )
        rec_score = float(row.get("recommendation_score") or 0)
        neg_conf = float(row.get("negotiation_confidence") or 0)
        deal_p = float(row.get("deal_probability") or 0)
        neg_risk = float(row.get("negotiation_risk") or 0)
        cs_conf = float(row.get("customer_success_confidence") or 0)
        cs_conv = float(row.get("cs_conversion_probability") or 0)
        validation_errs = list(row.get("validation_errors") or [])

        # Accuracy: success + low retries + no validation errors
        accuracy = 0.55 if ok else 0.15
        if ok and not validation_errs:
            accuracy += 0.2
        if retries == 0:
            accuracy += 0.15
        elif retries == 1:
            accuracy += 0.05
        else:
            notes.append("retries")
        if selected:
            accuracy += 0.1
        accuracy = _clamp(accuracy)

        conflict_rate = _clamp(conflicts / 5.0) if conflicts else 0.0
        if conflicts:
            notes.append(f"conflicts:{conflicts}")

        decision_quality = 0.3
        if selected:
            decision_quality = 0.4 + d_score * 0.35 + d_conf * 0.25
            if conflicts:
                decision_quality -= min(0.2, conflicts * 0.05)
        else:
            # No decision is OK for greeting / early-return
            wf = str(row.get("routed_workflow") or row.get("detected_intent") or "")
            if "greeting" in wf or wf in ("", "pass_through", "general"):
                decision_quality = 0.7
                notes.append("no_decision_expected")
            else:
                decision_quality = 0.35
                notes.append("no_selection")
        decision_quality = _clamp(decision_quality)

        recommendation_quality = 0.4
        if rec_score > 0:
            recommendation_quality = _clamp(0.35 + rec_score * 0.55)
        elif selected:
            recommendation_quality = 0.55
        if row.get("recommendation_reuse_analysis") or row.get("recommendation_reuse_search"):
            recommendation_quality = _clamp(recommendation_quality + 0.05)

        negotiation_quality = 0.4
        if neg_conf > 0 or deal_p > 0:
            negotiation_quality = _clamp(
                0.3 + neg_conf * 0.35 + deal_p * 0.35 - neg_risk * 0.15
            )
        elif not row.get("negotiation_tokens"):
            negotiation_quality = 0.65  # not applicable

        customer_success_quality = 0.4
        if cs_conf > 0 or cs_conv > 0:
            customer_success_quality = _clamp(0.3 + cs_conf * 0.35 + cs_conv * 0.35)
            if row.get("cs_next_action"):
                customer_success_quality = _clamp(customer_success_quality + 0.05)
        elif not row.get("customer_success_tokens"):
            customer_success_quality = 0.65

        overall = _clamp(
            accuracy * 0.25
            + (1.0 - conflict_rate) * 0.10
            + decision_quality * 0.25
            + recommendation_quality * 0.15
            + negotiation_quality * 0.125
            + customer_success_quality * 0.125
        )

        return QualityScores(
            accuracy=round(accuracy, 3),
            conflict_rate=round(conflict_rate, 3),
            decision_quality=round(decision_quality, 3),
            recommendation_quality=round(recommendation_quality, 3),
            negotiation_quality=round(negotiation_quality, 3),
            customer_success_quality=round(customer_success_quality, 3),
            overall=round(overall, 3),
            notes=notes[:8],
        )
