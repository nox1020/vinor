from __future__ import annotations

from app.adaptive.interfaces import (
    STATE_ANALYZING,
    STATE_DONE,
    STATE_FAILED,
    STATE_READY,
    QualityReport,
    RecoveryPolicy,
    WorkflowState,
)
from app.adaptive.state import RuleWorkflowMachine


class RuleRecoveryPolicy(RecoveryPolicy):
    """Fail-soft recovery: no crash, no infinite loop, max one step back."""

    def __init__(self) -> None:
        self._machine = RuleWorkflowMachine()

    def recover(
        self,
        wf: WorkflowState,
        *,
        error: str = "",
        quality: QualityReport | None = None,
    ) -> WorkflowState:
        wf.recovery_count += 1
        # Cap recoveries to avoid loops
        if wf.recovery_count > 2:
            wf.skipped_steps.append("recovery_cap")
            return self._machine.advance(wf, STATE_FAILED, reason="recovery_cap")

        if error:
            wf.metadata["last_error"] = error[:200]
            # Soft landing: FAILED without crashing caller
            return self._machine.advance(wf, STATE_FAILED, reason=error[:80] or "error")

        if quality is not None:
            if quality.complete and quality.found_suitable:
                self._machine.advance(wf, STATE_READY, reason="quality_ok")
                return self._machine.advance(wf, STATE_DONE, reason="complete")
            if quality.needs_continue:
                # Partial success — mark DONE with continue flag (no loop)
                wf.metadata["needs_continue"] = True
                wf.skipped_steps.append("continue_deferred")
                if wf.state != STATE_READY:
                    self._machine.advance(wf, STATE_READY, reason="partial")
                return self._machine.advance(wf, STATE_DONE, reason="needs_continue")
            if not quality.complete:
                # Empty / weak — recover to ANALYZING once, then DONE
                if wf.recovery_count <= 1 and wf.state in (STATE_READY, STATE_ANALYZING, "SEARCHING"):
                    self._machine.advance(wf, STATE_ANALYZING, reason="weak_quality")
                    wf.skipped_steps.append("weak_to_analyzing")
                    return self._machine.advance(wf, STATE_DONE, reason="recovered_done")
                return self._machine.advance(wf, STATE_FAILED, reason="incomplete")

        return self._machine.advance(wf, STATE_DONE, reason="default_recover")
