"""The open estimate-context assembly-load model (issue #201) — assemblies
bound to a specific bid/estimate item, as opposed to the org-level reusable
templates in :mod:`estimating_tools.assemblies.model`.

Pure: stdlib only. Carries NO org data (rates, crews, cost-code maps) — those
are passed in or resolved against the org's BidSheet.ai rate library / cost-code
system by the skill. Only the mechanism (the roll-up contract and its two
silent traps) is enforced here, in :func:`plan_assembly_load`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoadComponent:
    """One line of an estimate-context assembly.

    For a production-basis labor component the BidSheet.ai roll-up is
    ``cost = quantity × unit_cost × production_rate`` where ``production_rate``
    lives on the parent :class:`LoadAssembly`. So the legible crew shape is
    ``quantity`` = headcount, ``unit_cost`` = hourly rate — do NOT pre-multiply
    men × hours into ``quantity``; the assembly's ``production_rate`` carries the
    duration. ``labor_cost_basis`` selects that behavior ("production", the
    default) versus a plain extended ``quantity × unit_cost`` ("flat" — unit_cost
    is the all-in labor cost per unit, no duration)."""

    component_type: str
    name: str
    quantity: float = 1.0
    unit: str = ""
    unit_cost: float | None = None
    rate_ref: str | None = None
    trade: str = ""
    description: str = ""
    labor_cost_basis: str = "production"


@dataclass
class LoadAssembly:
    """An assembly to load onto a bid/estimate item. ``production_rate`` (in
    ``production_unit``, typically HOURS) is REQUIRED whenever the assembly
    carries a production-basis labor component — leaving it unset makes that
    labor roll up $0."""

    name: str
    assembly_type: str = ""
    cost_code: str | None = None
    description: str = ""
    production_rate: float | None = None
    production_unit: str = "HOURS"
    components: list[LoadComponent] = field(default_factory=list)


@dataclass
class AssemblyLoadItem:
    """Assemblies bound to one bid/estimate item, keyed by its estimate item id
    (``bid_item_code`` is carried for trace/display only)."""

    estimate_item_id: int
    assemblies: list[LoadAssembly] = field(default_factory=list)
    bid_item_code: str = ""


@dataclass
class CanonicalAssemblyLoad:
    """The assemblies to load across an estimate's items."""

    items: list[AssemblyLoadItem] = field(default_factory=list)
