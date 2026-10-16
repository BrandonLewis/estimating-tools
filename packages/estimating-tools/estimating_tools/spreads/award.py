"""Turn a leveled Spread + an award decision into a plan of subcontractor
allocations. Pure: no MCP/Django.

Strategies: "vendor" (award one vendor's included bid cells) and "manual" (a list
of {work_package_item_id, vendor_id} selections, allowing multiple subs per item).
Each awarded cell -> an AwardEntry with allocation_type "full" (cell covers the
item's full quantity) or "quantity" (partial; value = the bid quantity). Per item,
the remainder (full - allocated, clamped at 0) is the self-perform / unallocated
portion.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.artifacts import format_money, format_qty, md_table


@dataclass
class AwardEntry:
    work_package_item_id: int
    quote_line_item_id: int | None
    vendor_id: int
    vendor_name: str
    item_label: str
    allocation_type: str            # "full" | "quantity"
    value: float | None             # None for "full"; bid quantity for "quantity"
    unit_price: float | None
    extended_amount: float | None


@dataclass
class ItemCoverage:
    work_package_item_id: int
    item_label: str
    full_quantity: float | None
    allocated_quantity: float
    remainder: float
    fully_allocated: bool


@dataclass
class AwardPlan:
    entries: list[AwardEntry] = field(default_factory=list)
    coverage: list[ItemCoverage] = field(default_factory=list)
    strategy: str = ""
    vendor_id: int | None = None
    selection: list[dict] | None = None


def _label(row) -> str:
    return f"{row.item_number} ({row.schedule_name})" if row.schedule_name else row.item_number


def _vendor_name(spread, vendor_id) -> str:
    for v in spread.vendors:
        if v["vendor_id"] == vendor_id:
            return v.get("display_name", "") or ""
    return ""


def _entry_for(row, cell, spread) -> AwardEntry:
    """Build an AwardEntry for an awarded `bid` cell."""
    if cell.quote_line_item_id is None:
        raise ValueError(
            f"cannot award item {row.work_package_item_id} to vendor {cell.vendor_id}:"
            f" quote line has no id"
        )
    full_qty = row.quantity
    is_partial = bool(cell.is_partial) or (
        full_qty is not None and cell.quantity is not None and cell.quantity < full_qty
    )
    if is_partial:
        allocation_type, value = "quantity", cell.quantity
    else:
        allocation_type, value = "full", None
    return AwardEntry(
        work_package_item_id=row.work_package_item_id,
        quote_line_item_id=cell.quote_line_item_id,
        vendor_id=cell.vendor_id,
        vendor_name=_vendor_name(spread, cell.vendor_id),
        item_label=_label(row),
        allocation_type=allocation_type,
        value=value,
        unit_price=cell.unit_price,
        extended_amount=cell.extended_amount,
    )


def _allocated_qty(entry, row) -> float:
    """A 'full' award counts as the item's full quantity; 'quantity' counts its value."""
    if entry.allocation_type == "full":
        return row.quantity if row.quantity is not None else 0.0
    return entry.value or 0.0


def plan_award(spread, strategy, vendor_id=None, selection=None) -> AwardPlan:
    if strategy == "vendor" and vendor_id is None:
        raise ValueError("vendor strategy requires vendor_id")
    if strategy == "manual" and selection is None:
        raise ValueError("manual strategy requires selection")

    rows_by_id = {r.work_package_item_id: r for r in spread.rows}

    # Collect (row, cell) awards in a deterministic order.
    awards: list[tuple] = []  # (row, cell)
    if strategy == "vendor":
        for row in spread.rows:
            cell = row.cells.get(vendor_id)
            if cell is not None and cell.status == "bid":
                awards.append((row, cell))
    elif strategy == "manual":
        for sel in selection:
            if "work_package_item_id" not in sel or "vendor_id" not in sel:
                raise ValueError(
                    f"malformed selection entry (needs work_package_item_id and vendor_id): {sel!r}"
                )
        for sel in selection:
            row = rows_by_id.get(sel["work_package_item_id"])
            if row is None:
                continue
            cell = row.cells.get(sel["vendor_id"])
            if cell is not None and cell.status == "bid":
                awards.append((row, cell))
    else:
        raise ValueError(f"unknown strategy: {strategy!r}")

    entries = [_entry_for(row, cell, spread) for row, cell in awards]

    # Per-item coverage: sum allocated across this plan's entries for the item.
    allocated_by_item: dict[int, float] = {}
    for (row, cell), entry in zip(awards, entries):
        allocated_by_item[row.work_package_item_id] = (
            allocated_by_item.get(row.work_package_item_id, 0.0) + _allocated_qty(entry, row)
        )

    # Coverage rows: every item touched by the strategy. For "vendor", that is every
    # row (so un-bid items show as 0 allocated). For "manual", the items named in the
    # selection (deduped, first-seen order).
    if strategy == "vendor":
        cov_rows = list(spread.rows)
    else:
        seen, cov_rows = set(), []
        for sel in selection:
            wid = sel["work_package_item_id"]
            if wid in seen:
                continue
            seen.add(wid)
            row = rows_by_id.get(wid)
            if row is not None:
                cov_rows.append(row)

    coverage = []
    for row in cov_rows:
        full_qty = row.quantity
        allocated = allocated_by_item.get(row.work_package_item_id, 0.0)
        remainder = max(0.0, (full_qty - allocated)) if full_qty is not None else 0.0
        coverage.append(ItemCoverage(
            work_package_item_id=row.work_package_item_id,
            item_label=_label(row),
            full_quantity=full_qty,
            allocated_quantity=allocated,
            remainder=remainder,
            fully_allocated=(full_qty is not None and remainder == 0.0),
        ))

    return AwardPlan(entries=entries, coverage=coverage, strategy=strategy,
                     vendor_id=vendor_id if strategy == "vendor" else None,
                     selection=selection if strategy == "manual" else None)


def render_award_plan(plan) -> str:
    headers = ["Item", "Vendor", "Allocation", "Qty", "Unit price"]
    rows = [
        [e.item_label, e.vendor_name, e.allocation_type, format_qty(e.value),
         format_money(e.unit_price)]
        for e in plan.entries
    ]
    out = f"Award plan (strategy: {plan.strategy})\n\n" + md_table(headers, rows) + "\n"
    out += "\nCoverage (remainder = self-perform / unallocated):\n"
    for c in plan.coverage:
        suffix = " (self-perform)" if c.remainder and c.remainder > 0 else ""
        out += (f"- {c.item_label}: allocated {format_qty(c.allocated_quantity)} of "
                f"{format_qty(c.full_quantity)} — remainder {format_qty(c.remainder)}{suffix}\n")
    return out
