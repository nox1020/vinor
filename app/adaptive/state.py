from __future__ import annotations

from app.adaptive.interfaces import (
    STATE_ANALYZING,
    STATE_DONE,
    STATE_FAILED,
    STATE_INIT,
    STATE_READY,
    STATE_SEARCHING,
    WorkflowMachine,
    WorkflowState,
)

# Allowed transitions (no loops beyond DONE/FAILED terminals)
_ALLOWED: dict[str, set[str]] = {
    STATE_INIT: {STATE_SEARCHING, STATE_ANALYZING, STATE_READY, STATE_DONE, STATE_FAILED},
    STATE_SEARCHING: {STATE_ANALYZING, STATE_READY, STATE_FAILED, STATE_DONE},
    STATE_ANALYZING: {STATE_READY, STATE_SEARCHING, STATE_FAILED, STATE_DONE},
    STATE_READY: {STATE_DONE, STATE_FAILED, STATE_ANALYZING},
    STATE_DONE: {STATE_DONE},
    STATE_FAILED: {STATE_FAILED, STATE_READY, STATE_DONE},
}


class RuleWorkflowMachine(WorkflowMachine):
    def start(self, *, route: str) -> WorkflowState:
        wf = WorkflowState(state=STATE_INIT, route=route or "")
        wf.history.append(f"start:{route or 'none'}")
        return wf

    def advance(self, wf: WorkflowState, target: str, *, reason: str = "") -> WorkflowState:
        target = (target or "").strip().upper() or STATE_FAILED
        allowed = _ALLOWED.get(wf.state, set())
        if target not in allowed:
            # Recovery-safe: jump to FAILED instead of illegal loop
            wf.skipped_steps.append(f"illegal:{wf.state}->{target}")
            if STATE_FAILED in allowed or wf.state != STATE_FAILED:
                wf.transition(STATE_FAILED, reason=f"illegal_transition:{reason or target}")
            return wf
        wf.transition(target, reason=reason)
        return wf
