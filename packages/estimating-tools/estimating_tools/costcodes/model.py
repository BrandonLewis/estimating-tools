"""The open cost-code-system model — an org's cost types + a hierarchy of activity codes.
Pure: stdlib only. Fields map to BidSheet.ai's create_cost_code_system / create_cost_type /
create_activity_code. References to cost type and parent are by CODE; the push resolves them
to ids within the created system."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostType:
    """A cost type (Labor/Material/Equipment/…) within a system. code is unique per system."""

    code: str
    name: str = ""
    description: str = ""
    sort_order: int = 0


@dataclass
class ActivityCode:
    """One activity (cost) code. cost_type_code names its CostType (by code, may be "");
    parent_code names its parent ActivityCode (by code, "" = a root). Both are resolved to
    ids at push time within the system."""

    code: str
    source_code: str = ""
    description: str = ""
    category: str = ""
    cost_type_code: str = ""
    parent_code: str = ""
    default_unit: str = ""
    structure_tags: list[str] = field(default_factory=list)
    notes: str = ""
    sort_order: int = 0
    is_active: bool = True
    level: int = 0


@dataclass
class CanonicalCostCodeSystem:
    """An org's cost-code system. activity_codes is topologically ordered (parents first)."""

    name: str
    description: str = ""
    version: str = ""
    source_system: str = ""
    edition: str = ""
    composition: str = "composed"  # "composed" | "monolithic"
    cost_types: list[CostType] = field(default_factory=list)
    activity_codes: list[ActivityCode] = field(default_factory=list)
