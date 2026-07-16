from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LandDocument:
    code: str
    text: str
    city: str
    location: str
    category: str
    status: str
    tags: list[str]
    price_total: int
    area_total: int

