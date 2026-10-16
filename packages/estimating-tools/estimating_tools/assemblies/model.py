"""The open assembly-library model — an org's reusable assembly templates.
Pure: stdlib only."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Component:
    """One line of an assembly. component_type is one of labor/material/equipment/
    subcontractor/other. unit_cost is the inline cost; rate_ref optionally names a
    rate-library rate. On a labor/equipment/material component, rate_ref resolves to the
    org's matching rate id at push (routed by component_type — BidManager #593); on a
    subcontractor/other component it is non-routable and kept as an inline-cost flag."""

    component_type: str
    name: str
    quantity: float = 1.0
    unit: str = ""
    unit_cost: float | None = None
    rate_ref: str | None = None
    trade: str = ""
    description: str = ""


@dataclass
class Assembly:
    """A reusable assembly template. cost_code is an optional code string resolved to
    an activity code at push time."""

    name: str
    assembly_type: str = ""
    cost_code: str | None = None
    description: str = ""
    components: list[Component] = field(default_factory=list)


@dataclass
class CanonicalAssemblyLibrary:
    """An org's assembly templates."""

    assemblies: list[Assembly] = field(default_factory=list)
