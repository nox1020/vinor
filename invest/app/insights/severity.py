"""Insight severity / importance levels."""

from __future__ import annotations

from enum import IntEnum


class InsightSeverity(IntEnum):
    """Priority for sorting and presentation (higher = more urgent)."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return self.name
