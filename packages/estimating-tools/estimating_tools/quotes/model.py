"""The open vendor-quote model — the agent extracts a quote into this shape."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QuoteLine:
    schedule_name: str
    item_number: str
    unit_price: float | None = None
    amount: float | None = None
    quantity: float | None = None
    is_included: bool = True
    is_alternate: bool = False
    exclusion_notes: str | None = None
    line_name: str | None = None  # the spec line this prices
    folded_into: str | None = None  # name of the vendor line that carries this scope


@dataclass
class CanonicalQuote:
    """A vendor's quote on a scope. `vendor_name` is the free-text fallback (always kept);
    `vendor_id` optionally links the quote to a directory Organization (resolved during
    capture — when set, BidSheet.ai shows the org's display name / DBE / contacts).
    `lines` reference bid items by (schedule_name, item_number)."""

    vendor_name: str
    work_package_name: str
    amount: float | None = None
    vendor_id: int | None = None
    is_dbe: bool = False
    contact_info: str | None = None
    notes: str | None = None
    lines: list[QuoteLine] = field(default_factory=list)
    quote_date: str | None = None  # ISO YYYY-MM-DD, orders revisions
    quote_ref: str | None = None
    surcharge: float | None = None  # fuel-type surcharge, fraction
    conditions: dict[str, str] = field(default_factory=dict)  # fills the package conditions grid
