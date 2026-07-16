from __future__ import annotations

from app.conversation.identity import RuleIdentityResolver
from app.conversation.intent import RuleIntentResolver
from app.conversation.interfaces import ConversationManager
from app.conversation.manager import DefaultConversationManager
from app.conversation.roles import RuleRoleResolver
from app.conversation.session import FileSessionStore
from app.conversation.workflow import RuleWorkflowResolver
from app.workflow.config import workflow_engine_enabled
from app.workflow.di import make_workflow_engine


def make_conversation_manager() -> ConversationManager:
    engine = make_workflow_engine() if workflow_engine_enabled() else None
    return DefaultConversationManager(
        identity=RuleIdentityResolver(),
        roles=RuleRoleResolver(),
        intents=RuleIntentResolver(),
        workflows=RuleWorkflowResolver(),
        sessions=FileSessionStore(),
        engine=engine,
    )
