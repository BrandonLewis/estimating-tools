"""Compute a leveled Spread from fetched BidSheet.ai data. Pure: no MCP/Django.

Cell extended = unit_price * quantity (fallback to the line's stored `amount`).
Best-per-item ranks on unit_price among included lines. No line / excluded line /
alternate line = coverage gap (never $0). Full item quantity comes from
list_bid_items.

Alternates: a line with ``is_alternate`` true (and therefore ``is_included``
false -- the two are never both true in a correctly-planned line) becomes
``Cell(status="alternate")``: it is priced the same way a bid cell is, but it is
never eligible for best-per-item, outliers, the base ``total``/``items_bid``, or
best-of-breed -- it stays a base coverage gap (reason "alternate") and instead
feeds ``VendorTotal.total_with_alternates`` / ``items_bid_with_alternates`` (base +
priced alternates) and sets ``Spread.has_alternates``.

Defense in depth: ``build_spread`` checks ``is_alternate`` BEFORE ``is_included``,
so a line that somehow carries both true (a bad write upstream) is still always
treated as an alternate and never slips into the base -- the ordering, not just the
data contract, keeps an alternate out of the base total.
"""
from __future__ import annotations

from estimating_tools.spreads.model import Cell, Row, Spread, VendorTotal

OUTLIER_FACTOR = 1.5


def _num(value):
    """Parse a decimal-string/number to float, or None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(ln):
    """unit_price, quantity, extended_amount for a line -- extended prefers
    unit_price * quantity, falling back to the line's stored `amount`. Shared by
    the bid and alternate paths in `build_spread` so both price a line the same
    way."""
    unit_price = _num(ln.get("unit_price"))
    qty = _num(ln.get("quantity"))
    extended = None
    if unit_price is not None and qty is not None:
        extended = unit_price * qty
    if extended is None:
        extended = _num(ln.get("amount"))
    return unit_price, qty, extended


def build_spread(items, bid_items, quotes, lines_by_quote) -> Spread:
    """Build a leveled Spread from fetched BidSheet.ai data.

    Null-unit-price bid invariant
    --------------------------------
    An included line ("bid") with a null per-unit ``unit_price`` can still
    contribute an ``extended_amount`` via its stored ``amount`` field, and it
    counts toward ``items_bid`` and the vendor total when that fallback amount
    is present.  However, it is *never* eligible to be the per-item best:
    best-per-item ranking uses ``unit_price`` only (via the ``priced`` filter),
    so a line without a unit price is always excluded from that competition and
    its cell renders with a blank price column.

    A fully-null included line (no ``unit_price``, no ``quantity``, and no
    ``amount``) receives ``status="bid"`` but ``extended_amount=None``; it
    therefore contributes nothing to the vendor total, is not counted in
    ``items_bid``, and is not added to the gaps list.  This is intentional:
    such a line represents a stub acknowledgment, not a priced or gapped
    position.  Cycle 1c inherits this invariant unchanged.
    """
    bid_by_id = {b["id"]: b for b in bid_items}
    # line lookup: (quote_id, work_package_item_id) -> line
    line_lookup = {}
    for quote_id, lines in lines_by_quote.items():
        for ln in lines:
            line_lookup[(quote_id, ln["work_package_item_id"])] = ln

    vendors = [
        {"vendor_id": q["vendor_id"], "quote_id": q["id"],
         "display_name": q.get("vendor_display_name") or q.get("vendor_name") or "",
         "is_dbe": bool(q.get("is_dbe")), "status": q.get("status", "")}
        for q in quotes
    ]

    rows: list[Row] = []
    gaps: list[dict] = []
    outliers: list[dict] = []

    for it in items:
        bid = bid_by_id.get(it.get("project_bid_item_id"), {})
        full_qty = _num(bid.get("quantity"))
        row = Row(
            work_package_item_id=it["id"],
            project_bid_item_id=it.get("project_bid_item_id"),
            item_code=it.get("item_code"),
            item_number=it.get("item_number", ""),
            schedule_name=it.get("schedule_name"),
            description=bid.get("description", ""),
            unit=bid.get("unit", ""),
            quantity=full_qty,
        )
        for v in vendors:
            ln = line_lookup.get((v["quote_id"], it["id"]))
            if ln is None:
                row.cells[v["vendor_id"]] = Cell(vendor_id=v["vendor_id"], status="no_bid")
                gaps.append({"vendor_id": v["vendor_id"], "work_package_item_id": it["id"],
                             "reason": "no_bid"})
                continue
            # Check is_alternate BEFORE is_included: an alternate is never in the
            # base regardless of what is_included says (defense in depth -- a line
            # that somehow has both true must still never reach the bid branch).
            if ln.get("is_alternate"):
                unit_price, qty, extended = _price(ln)
                row.cells[v["vendor_id"]] = Cell(
                    vendor_id=v["vendor_id"], status="alternate",
                    quote_line_item_id=ln["id"], is_included=False, is_alternate=True,
                    unit_price=unit_price, quantity=qty, extended_amount=extended,
                    exclusion_notes=ln.get("exclusion_notes", "") or "")
                gaps.append({"vendor_id": v["vendor_id"], "work_package_item_id": it["id"],
                             "reason": "alternate"})
                continue
            if not ln.get("is_included", True):
                row.cells[v["vendor_id"]] = Cell(
                    vendor_id=v["vendor_id"], status="excluded",
                    quote_line_item_id=ln["id"], is_included=False,
                    exclusion_notes=ln.get("exclusion_notes", "") or "")
                gaps.append({"vendor_id": v["vendor_id"], "work_package_item_id": it["id"],
                             "reason": "excluded"})
                continue
            unit_price, qty, extended = _price(ln)
            row.cells[v["vendor_id"]] = Cell(
                vendor_id=v["vendor_id"], status="bid", quote_line_item_id=ln["id"],
                unit_price=unit_price, quantity=qty, extended_amount=extended,
                is_included=True,
                is_partial=(qty is not None and full_qty is not None and qty < full_qty),
            )

        # best-per-item on unit_price among bid cells with a price
        priced = [c for c in row.cells.values() if c.status == "bid" and c.unit_price is not None]
        if priced:
            best = min(priced, key=lambda c: c.unit_price)
            row.best_vendor_id = best.vendor_id
            row.best_unit_price = best.unit_price
            if full_qty is not None:
                row.best_extended = best.unit_price * full_qty
            for c in priced:
                if c.unit_price >= OUTLIER_FACTOR * best.unit_price and c.vendor_id != best.vendor_id:
                    outliers.append({"vendor_id": c.vendor_id,
                                     "work_package_item_id": it["id"],
                                     "unit_price": c.unit_price,
                                     "best_unit_price": best.unit_price})
        rows.append(row)

    # per-vendor totals + coverage
    items_total = len(rows)
    vendor_totals: list[VendorTotal] = []
    for v in vendors:
        total = 0.0
        items_bid = 0
        alt_total = 0.0
        alt_items_bid = 0
        for row in rows:
            c = row.cells.get(v["vendor_id"])
            if c is not None and c.status == "bid" and c.extended_amount is not None:
                total += c.extended_amount
                items_bid += 1
            if c is not None and c.status == "alternate" and c.extended_amount is not None:
                alt_total += c.extended_amount
                alt_items_bid += 1
        vendor_totals.append(VendorTotal(
            vendor_id=v["vendor_id"], display_name=v["display_name"],
            is_dbe=v["is_dbe"], status=v["status"], total=total,
            items_bid=items_bid, items_total=items_total,
            total_with_alternates=total + alt_total,
            items_bid_with_alternates=items_bid + alt_items_bid))

    best_of_breed_total = sum(r.best_extended for r in rows if r.best_extended is not None)
    has_alternates = any(c.status == "alternate" for row in rows for c in row.cells.values())

    return Spread(vendors=vendors, rows=rows, vendor_totals=vendor_totals,
                  best_of_breed_total=best_of_breed_total, outliers=outliers, gaps=gaps,
                  has_alternates=has_alternates)
