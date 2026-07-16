from __future__ import annotations

from app.supervisor.manager import DefaultSupervisor, DefaultSupervisorManager
from app.supervisor.policy import RuleExecutionPolicy
from app.supervisor.router import RuleRouter
from app.supervisor.interfaces import SupervisorManager


def make_supervisor_manager() -> SupervisorManager:
    supervisor = DefaultSupervisor(router=RuleRouter(), policy=RuleExecutionPolicy())
    return DefaultSupervisorManager(supervisor)
