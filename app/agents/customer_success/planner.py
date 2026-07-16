from __future__ import annotations

from typing import Any

from app.agents.customer_success.actions import RuleNextActionBuilder
from app.agents.customer_success.config import customer_success_hint_budget_chars
from app.agents.customer_success.conversion import RuleConversionAnalyzer
from app.agents.customer_success.interfaces import (
    ConversionAnalyzer,
    CustomerSuccessPlan,
    CustomerSuccessRequest,
    FollowUpPlanner,
    NextActionBuilder,
)


class RuleFollowUpPlanner(FollowUpPlanner):
    def __init__(
        self,
        *,
        conversion: ConversionAnalyzer | None = None,
        actions: NextActionBuilder | None = None,
    ):
        self._conversion = conversion or RuleConversionAnalyzer()
        self._actions = actions or RuleNextActionBuilder()

    def plan(self, req: CustomerSuccessRequest) -> CustomerSuccessPlan:
        shared = dict(req.shared or {})
        profile, negotiation, recommendation, workflow, flags = self._gather(shared)

        conv_p, stage = self._conversion.analyze(
            profile=profile,
            negotiation=negotiation,
            recommendation=recommendation,
            workflow=workflow,
            shared=shared,
        )
        next_action, ftype, ftime, priority, urgency = self._actions.build(
            stage=stage,
            conversion_probability=conv_p,
            negotiation=negotiation,
            profile=profile,
            workflow=workflow,
        )
        reason = self._reason(stage, next_action, negotiation, recommendation)
        confidence = min(
            0.95,
            0.3
            + (0.15 if flags["reuse_customer_profile"] else 0)
            + (0.15 if flags["reuse_negotiation"] else 0)
            + (0.1 if flags["reuse_recommendation"] else 0)
            + (0.1 if flags["reuse_analysis"] else 0)
            + (0.1 if flags["reuse_workflow"] else 0)
            + conv_p * 0.2,
        )
        hint = self._compact_hint(
            stage=stage,
            next_action=next_action,
            ftime=ftime,
            priority=priority,
            budget_chars=int(req.context_budget_chars or customer_success_hint_budget_chars()),
        )
        return CustomerSuccessPlan(
            customer_stage=stage,
            next_action=next_action,
            followup_type=ftype,
            followup_time=ftime,
            priority=priority,
            conversion_probability=conv_p,
            urgency=urgency,
            reason=reason,
            confidence=round(confidence, 3),
            compact_hint=hint,
            customer_success_tokens=(len(hint) + 3) // 4 if hint else 0,
            reuse_analysis=flags["reuse_analysis"],
            reuse_recommendation=flags["reuse_recommendation"],
            reuse_negotiation=flags["reuse_negotiation"],
            reuse_customer_profile=flags["reuse_customer_profile"],
            reuse_workflow=flags["reuse_workflow"],
            reuse_planning=flags["reuse_planning"],
            metadata={"route": req.route},
        )

    def _gather(
        self, shared: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, bool]]:
        flags = {
            "reuse_analysis": bool(shared.get("analysis_categories") or shared.get("property_analysis_agent")),
            "reuse_recommendation": bool(
                shared.get("recommended_code") or shared.get("recommendation_items")
            ),
            "reuse_negotiation": bool(shared.get("negotiation_plan")),
            "reuse_customer_profile": bool(shared.get("customer_profile") or shared.get("memory_prefs")),
            "reuse_workflow": False,
            "reuse_planning": bool(shared.get("reused_planning") or shared.get("planning_land_codes")),
        }

        profile = shared.get("customer_profile") if isinstance(shared.get("customer_profile"), dict) else {}
        if not profile:
            try:
                from app.agents.customer_memory.service import get_customer_profile

                profile = get_customer_profile() or {}
                if profile:
                    flags["reuse_customer_profile"] = True
            except Exception:
                profile = {}

        negotiation = shared.get("negotiation_plan") if isinstance(shared.get("negotiation_plan"), dict) else {}
        if not negotiation:
            try:
                from app.agents.negotiation.service import get_negotiation_plan

                negotiation = get_negotiation_plan() or {}
                if negotiation:
                    flags["reuse_negotiation"] = True
            except Exception:
                negotiation = {}

        recommendation: dict[str, Any] = {}
        items = shared.get("recommendation_items") or []
        if items and isinstance(items[0], dict):
            recommendation = {
                "code": items[0].get("property_code"),
                "score": items[0].get("score"),
            }
            flags["reuse_recommendation"] = True
        elif shared.get("recommended_code"):
            recommendation = {"code": shared.get("recommended_code"), "score": 0.5}
            flags["reuse_recommendation"] = True
        else:
            try:
                from app.agents.recommendation.service import get_recommendation_obs

                obs = get_recommendation_obs() or {}
                if obs.get("selected_property") or obs.get("recommendation_score"):
                    recommendation = {
                        "code": obs.get("selected_property"),
                        "score": obs.get("recommendation_score"),
                    }
                    flags["reuse_recommendation"] = True
            except Exception:
                pass

        workflow: dict[str, Any] = {}
        try:
            from app.conversation.service import get_conversation_obs

            conv = get_conversation_obs() or {}
            if conv.get("workflow") and conv.get("workflow") not in ("", "none"):
                workflow = {
                    "workflow": conv.get("workflow"),
                    "workflow_state": conv.get("workflow_state") or conv.get("conversation_state"),
                }
                flags["reuse_workflow"] = True
        except Exception:
            pass
        if shared.get("workflow"):
            workflow.setdefault("workflow", shared.get("workflow"))
            flags["reuse_workflow"] = True

        return profile, negotiation, recommendation, workflow, flags

    def _reason(
        self,
        stage: str,
        next_action: str,
        negotiation: dict[str, Any],
        recommendation: dict[str, Any],
    ) -> str:
        bits = [f"stage={stage}", f"action={next_action}"]
        if negotiation.get("recommended_strategy"):
            bits.append(f"neg={negotiation.get('recommended_strategy')}")
        if recommendation.get("code"):
            bits.append(f"rec={recommendation.get('code')}")
        return "|".join(bits)[:80]

    def _compact_hint(
        self,
        *,
        stage: str,
        next_action: str,
        ftime: str,
        priority: str,
        budget_chars: int,
    ) -> str:
        budget = max(30, min(budget_chars or 55, 60))
        header = "=== پیگیری === "
        body = f"{stage[:8]}|{next_action[:12]}|{ftime}|{priority[:1]}"
        room = budget - len(header)
        if len(body) > room:
            body = body[: max(0, room - 1)] + "…"
        return (header + body)[:budget]
