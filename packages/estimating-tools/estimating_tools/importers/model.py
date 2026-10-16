"""The open canonical estimate model — the importer target and interchange format."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class LineItem:
    item_number: str
    description: str = ""
    item_code: str | None = None
    quantity: float | None = None
    unit: str = ""
    unit_price: float | None = None
    total: float | None = None
    breakdown: dict | None = None


@dataclass
class Schedule:
    name: str
    items: list[LineItem] = field(default_factory=list)


@dataclass
class CanonicalEstimate:
    """project: {name (required), bid_date?, owner?, source?}; schedules: >=1."""

    project: dict
    schedules: list[Schedule] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "CanonicalEstimate":
        schedules = [
            Schedule(name=s["name"], items=[LineItem(**it) for it in s.get("items", [])])
            for s in data.get("schedules", [])
        ]
        return cls(project=dict(data.get("project", {})), schedules=schedules)

    @classmethod
    def from_json(cls, text: str) -> "CanonicalEstimate":
        return cls.from_dict(json.loads(text))
