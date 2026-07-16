from __future__ import annotations

import time

from app.supervisor.interfaces import (
    ExecutionPolicy,
    Router,
    Supervisor,
    SupervisorManager,
    SupervisorOutcome,
    SupervisorRequest,
)
from app.supervisor.workflow import build_workflow


class DefaultSupervisor(Supervisor):
    def __init__(self, *, router: Router, policy: ExecutionPolicy):
        self._router = router
        self._policy = policy

    def decide(self, req: SupervisorRequest) -> SupervisorOutcome:
        t0 = time.perf_counter()
        route = self._router.route(req)
        flags = self._policy.resolve(route, req=req)
        workflow = build_workflow(route, flags, reason=f"rule:{route}")
        return SupervisorOutcome(
            workflow=workflow,
            routing_time_ms=int((time.perf_counter() - t0) * 1000),
        )


class DefaultSupervisorManager(SupervisorManager):
    def __init__(self, supervisor: Supervisor):
        self._supervisor = supervisor

    def orchestrate(self, req: SupervisorRequest) -> SupervisorOutcome:
        return self._supervisor.decide(req)
