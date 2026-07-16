from __future__ import annotations

from app.conversation.interfaces import (
    STATE_COLLECTING,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_START,
    STATE_WAITING,
    ConversationSession,
    WorkflowDefinition,
)

_ALLOWED: dict[str, set[str]] = {
    STATE_START: {STATE_COLLECTING, STATE_COMPLETED, STATE_FAILED},
    STATE_COLLECTING: {STATE_WAITING, STATE_COMPLETED, STATE_FAILED, STATE_COLLECTING},
    STATE_WAITING: {STATE_COLLECTING, STATE_COMPLETED, STATE_FAILED},
    STATE_COMPLETED: {STATE_COMPLETED, STATE_START},
    STATE_FAILED: {STATE_FAILED, STATE_START, STATE_COLLECTING},
}


def transition(session: ConversationSession, new_state: str) -> ConversationSession:
    new_state = (new_state or "").strip().upper() or STATE_FAILED
    allowed = _ALLOWED.get(session.state, set())
    if new_state not in allowed:
        session.state = STATE_FAILED
        session.metadata["illegal_transition"] = True
        return session
    session.state = new_state
    return session


def missing_fields(defn: WorkflowDefinition, collected: dict) -> list[str]:
    missing = []
    for step in defn.steps:
        if not step.required:
            continue
        val = collected.get(step.field)
        if val is None or str(val).strip() == "":
            missing.append(step.field)
    return missing


def next_step(defn: WorkflowDefinition, collected: dict) -> str:
    miss = missing_fields(defn, collected)
    return miss[0] if miss else ""


def question_for_step(defn: WorkflowDefinition, step_id: str) -> str:
    for s in defn.steps:
        if s.id == step_id or s.field == step_id:
            return s.question
    return "لطفاً ادامه دهید."


def build_structured_object(session: ConversationSession) -> dict:
    return {
        "type": session.object_type or session.workflow_id,
        "workflow_id": session.workflow_id,
        "intent": session.intent,
        "role": session.role,
        "fields": dict(session.collected or {}),
        "status": session.state,
    }
