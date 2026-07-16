from __future__ import annotations

from app.workflow.engine import DefaultWorkflowEngine
from app.workflow.interfaces import WorkflowEngine
from app.workflow.registry import WorkflowRegistry


def make_workflow_engine() -> WorkflowEngine:
    return DefaultWorkflowEngine(registry=WorkflowRegistry())
