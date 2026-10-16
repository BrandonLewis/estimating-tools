"""Structured leveling result — the spread of vendor quotes over a package's items.
Pure: stdlib only."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Cell:
    """One vendor's price for one item. status in {"bid","excluded","no_bid"}."""

    vendor_id: int
    status: str
    quote_line_item_id: int | None = None
    unit_price: float | None = None
    quantity: float | None = None
    extended_amount: float | None = None
    is_included: bool = True
    is_partial: bool = False
    exclusion_notes: str = ""
    not_comparable: bool = False


@dataclass
class Row:
    """One package item across all vendors."""

    work_package_item_id: int
    project_bid_item_id: int | None
    item_code: str | None
    item_number: str
    schedule_name: str | None
    description: str
    unit: str
    quantity: float | None
    cells: dict[int, Cell] = field(default_factory=dict)
    best_vendor_id: int | None = None
    best_unit_price: float | None = None
    best_extended: float | None = None


@dataclass
class VendorTotal:
    vendor_id: int
    display_name: str
    is_dbe: bool
    status: str
    total: float
    items_bid: int
    items_total: int


@dataclass
class ScopeGroup:
    """A named scope priced differently across vendors. ``basis_row_ids`` is
    the comparable basis (tagged items ∪ fold targets); ``subtotals`` maps
    vendor_id -> all-in basis total (None = vendor does not cover the basis,
    folded coverage counting)."""

    name: str
    basis_row_ids: list[int] = field(default_factory=list)
    subtotals: dict[int, float | None] = field(default_factory=dict)
    best_vendor_id: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Spread:
    vendors: list[dict] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    vendor_totals: list[VendorTotal] = field(default_factory=list)
    best_of_breed_total: float = 0.0
    outliers: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    scope_groups: list[ScopeGroup] = field(default_factory=list)
    obtainable_single_vendor: dict | None = None
    best_of_breed_annotations: list[dict] = field(default_factory=list)
    best_of_breed_suppressed: bool = False
    obtainable_best_mix: float | None = None
    # why the mix is None: "" (n/a) | "flags" (a row/group's only prices
    # come from vendors who forbid separate acceptance) | "coverage"
    obtainable_best_mix_reason: str = ""
    condition_warnings: list[dict] = field(default_factory=list)
