"""Message type constants for Chat-First architecture.

Backward compatible: legacy messages without ``type`` are treated as ``text``.
"""
from __future__ import annotations

# Core
MSG_TEXT = "text"
MSG_AI = "ai"
MSG_SYSTEM = "system"
MSG_ADMIN = "admin"
MSG_CARD = "card"
MSG_TIMELINE = "timeline"
MSG_NOTIFICATION = "notification"
MSG_WARNING = "warning"
MSG_ERROR = "error"
MSG_PROGRESS = "progress"
MSG_STATUS = "status"
MSG_ATTACHMENT = "attachment"

# Domain-flavored (still messages; card payload carries detail)
MSG_MISSION = "mission"
MSG_VISIT = "visit"
MSG_DEAL = "deal"
MSG_COMMISSION = "commission"
MSG_PAYMENT = "payment"
MSG_CONTRACT = "contract"

ALL_MESSAGE_TYPES = frozenset(
    {
        MSG_TEXT,
        MSG_AI,
        MSG_SYSTEM,
        MSG_ADMIN,
        MSG_CARD,
        MSG_TIMELINE,
        MSG_NOTIFICATION,
        MSG_WARNING,
        MSG_ERROR,
        MSG_PROGRESS,
        MSG_STATUS,
        MSG_ATTACHMENT,
        MSG_MISSION,
        MSG_VISIT,
        MSG_DEAL,
        MSG_COMMISSION,
        MSG_PAYMENT,
        MSG_CONTRACT,
    }
)


def normalize_message_type(raw: str | None, *, role: str = "", source: str = "") -> str:
    t = str(raw or "").strip().lower()
    if t in ALL_MESSAGE_TYPES:
        return t
    src = str(source or "").strip().lower()
    if src == "admin_escalation":
        return MSG_ADMIN
    if src == "system" or src == "timeline":
        return MSG_SYSTEM if src == "system" else MSG_TIMELINE
    if str(role or "").strip() == "assistant":
        return MSG_AI
    return MSG_TEXT
