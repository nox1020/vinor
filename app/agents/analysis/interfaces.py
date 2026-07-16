from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AnalysisRequest:
    property_codes: tuple[str, ...] = ()
    message: str = ""
    route: str = ""
    audience: str = ""
    user_key: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    context_budget_chars: int = 160


@dataclass
class AnalysisCategoryResult:
    name: str
    summary: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    score: float = 0.5  # 0–1
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    ok: bool = True
    property_codes: list[str] = field(default_factory=list)
    categories: list[AnalysisCategoryResult] = field(default_factory=list)
    comparison: str = ""
    compact_hint: str = ""
    analysis_tokens: int = 0
    analysis_time_ms: int = 0
    cache_hit: bool = False
    reused_context: bool = False
    reused_rag: bool = False
    reused_memory: bool = False
    reused_planning: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class AnalysisStrategy(Protocol):
    def analyze(self, req: AnalysisRequest, lands: list[dict[str, Any]]) -> AnalysisResult:
        ...


class AnalysisCache(Protocol):
    def get(self, key: str) -> AnalysisResult | None:
        ...

    def put(self, key: str, result: AnalysisResult) -> None:
        ...


class AnalysisManager(Protocol):
    def run(self, req: AnalysisRequest) -> AnalysisResult:
        ...
