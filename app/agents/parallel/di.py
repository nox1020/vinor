from __future__ import annotations

from app.agents.di import make_agent_registry
from app.agents.interfaces import AgentRegistry
from app.agents.parallel.executor import ThreadPoolParallelExecutor
from app.agents.parallel.interfaces import ParallelCollaborationManager
from app.agents.parallel.manager import DefaultParallelCollaborationManager
from app.agents.parallel.merger import CompactAgentResultMerger
from app.agents.parallel.planner import RuleExecutionPlanner


def make_parallel_manager(registry: AgentRegistry | None = None) -> ParallelCollaborationManager:
    reg = registry or make_agent_registry()
    return DefaultParallelCollaborationManager(
        registry=reg,
        planner=RuleExecutionPlanner(),
        executor=ThreadPoolParallelExecutor(reg),
        merger=CompactAgentResultMerger(),
    )
