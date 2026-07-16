from __future__ import annotations

from app.adaptive.confidence import RuleConfidenceEstimator
from app.adaptive.controller import DefaultAdaptiveController
from app.adaptive.evaluator import RuleQualityEvaluator
from app.adaptive.interfaces import AdaptiveController
from app.adaptive.recovery import RuleRecoveryPolicy
from app.adaptive.retry import RuleRetryPolicy
from app.adaptive.state import RuleWorkflowMachine


def make_adaptive_controller() -> AdaptiveController:
    return DefaultAdaptiveController(
        machine=RuleWorkflowMachine(),
        confidence=RuleConfidenceEstimator(),
        evaluator=RuleQualityEvaluator(),
        retry=RuleRetryPolicy(),
        recovery=RuleRecoveryPolicy(),
    )
