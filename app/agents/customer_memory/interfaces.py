from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CustomerPreferences:
    budget_min: int | None = None
    budget_max: int | None = None
    locations: list[str] = field(default_factory=list)
    property_types: list[str] = field(default_factory=list)
    must_have: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "locations": list(self.locations),
            "property_types": list(self.property_types),
            "must_have": list(self.must_have),
            "avoid": list(self.avoid),
            "notes": list(self.notes),
        }


@dataclass
class CustomerProfile:
    user_key: str = ""
    preferences: CustomerPreferences = field(default_factory=CustomerPreferences)
    budget_profile: dict[str, Any] = field(default_factory=dict)
    location_preferences: list[str] = field(default_factory=list)
    property_interests: list[str] = field(default_factory=list)
    interaction_style: str = "neutral"  # short | detailed | decisive | exploratory | neutral
    last_activities: list[str] = field(default_factory=list)
    relationship_score: float = 0.0
    confidence: float = 0.0
    next_suggested_action: str = "continue_chat"
    preference_count: int = 0
    summary: str = ""
    compact_hint: str = ""
    customer_memory_tokens: int = 0
    profile_build_time_ms: int = 0
    cache_hit: bool = False
    reuse_memory: bool = False
    reuse_workflow: bool = False
    reuse_recommendation: bool = False
    reuse_analysis: bool = False
    reuse_planning: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_key": self.user_key,
            "preferences": self.preferences.to_dict(),
            "budget_profile": dict(self.budget_profile),
            "location_preferences": list(self.location_preferences),
            "property_interests": list(self.property_interests),
            "interaction_style": self.interaction_style,
            "last_activities": list(self.last_activities),
            "relationship_score": self.relationship_score,
            "confidence": self.confidence,
            "next_suggested_action": self.next_suggested_action,
            "preference_count": self.preference_count,
            "summary": self.summary,
        }


@dataclass
class CustomerMemoryRequest:
    user_key: str = ""
    message: str = ""
    route: str = ""
    audience: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    context_budget_chars: int = 70


class PreferenceExtractor(Protocol):
    def extract(
        self,
        *,
        message: str,
        memory_items: list[Any],
        shared: dict[str, Any],
    ) -> CustomerPreferences:
        ...


class RelationshipAnalyzer(Protocol):
    def analyze(
        self,
        *,
        preferences: CustomerPreferences,
        memory_items: list[Any],
        shared: dict[str, Any],
        conversation_obs: dict[str, Any],
    ) -> tuple[float, str, list[str]]:
        """Returns (relationship_score, interaction_style, last_activities)."""
        ...


class CustomerProfileBuilder(Protocol):
    def build(
        self,
        *,
        user_key: str,
        preferences: CustomerPreferences,
        relationship_score: float,
        interaction_style: str,
        last_activities: list[str],
        shared: dict[str, Any],
        budget_chars: int,
    ) -> CustomerProfile:
        ...


class CustomerMemoryCache(Protocol):
    def get(self, key: str) -> CustomerProfile | None:
        ...

    def put(self, key: str, profile: CustomerProfile) -> None:
        ...


class CustomerMemoryManager(Protocol):
    def build(self, req: CustomerMemoryRequest) -> CustomerProfile:
        ...
