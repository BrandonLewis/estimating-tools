"""A version-1 book's Checks figures, as a build from the fresh read model
would have written them (``heavybook.refresh`` refreshes the book's
BidSheet.ai column from these): ``(key, target, value)`` per row, ``key``
the row's (kind, code, description, measure), ``target`` the
``(tab, row kind, identity)`` of the row its Excel formula reads, or None.

The retired ``sheets/checks.py`` computed the same list through the code
build's layout plan; this is that list without the plan. Its estimate,
bid-total and schedule rows read named cells, bid-total rows and Schedule
rows, which the plan never named as targets, so their target is None here
too."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from estimating_tools.exchange import display

__all__ = ["figure_rows", "in_bid_fraction", "referenced"]

#: Excel's day zero: a date cell compares as its serial from here.
EXCEL_EPOCH = date(1899, 12, 30)
#: The first sheet-qualified cell a Checks formula reads (``'Tab'!$C$12``;
#: an unquoted name too).
_QUALIFIED = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_.]*))!\$?[A-Z]{1,3}\$?(\d+)")


def in_bid_fraction(wb, activity):
    """The share of ``activity``'s cost the payload's items carry (the shares
    to excluded items are dropped); a sum within 1e-12 of 1 is exactly 1."""
    f = sum((s.fraction for s in wb.shares_of_activity(activity.id)), Decimal(0))
    return Decimal(1) if abs(f - 1) < Decimal("1e-12") else f


def referenced(formula):
    """``(tab, row)`` of the first sheet-qualified cell ``formula`` reads, or
    None (no formula, or a reference Excel replaced with ``#REF!``)."""
    if not isinstance(formula, str) or not formula.startswith("="):
        return None
    m = _QUALIFIED.search(formula)
    if m is None:
        return None
    tab = m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)
    return tab, int(m.group(3))


def _key(value) -> str:
    return "" if value is None else str(value).strip()


def figure_rows(wb, tabs) -> list:
    """One entry per Checks row a version-1 build from ``wb`` wrote, in
    order. ``tabs``: the book's sheet titles by key (``cost_report``,
    ``crews``, ``bid_form``)."""
    cost, crews, bid = tabs["cost_report"], tabs["crews"], tabs["bid_form"]
    out = []

    def add(kind, code, desc, measure, target, value):
        out.append(((kind, _key(code), _key(desc), measure), target,
                    value if value is not None else Decimal(0)))

    for a in wb.activities:
        f = in_bid_fraction(wb, a)
        add("activity", a.code, a.name, "cost", None if f == 0 else (cost, "ACTIVITY", a.id),
            a.cost)
        add("activity", a.code, a.name, "man-hours", (cost, "ACTIVITY", a.id), a.manhours)
        if a.steps:
            add("activity", a.code, a.name, "shifts", (cost, "ACTIVITY", a.id),
                a.duration_shifts)
    for res in wb.resources:
        add("resource", "", res.name, "cost", (cost, "RESOURCE", res.id), res.cost)
    for item in wb.items:
        if item.scope == "excluded":
            add("item", item.item_number, item.description, "cost", None, item.total)
            continue
        add("item", item.item_number, item.description, "unit price", (cost, "ITEM", item.id),
            item.calculated_unit_price)
        # BidSheet.ai's ``calculate_total``: quantity x (manual price, else the
        # calculated unit price) -- not the stored ``total``.
        qty = item.quantity or Decimal(0)
        price = (item.estimated_unit_price if item.estimated_unit_price is not None
                 else (item.calculated_unit_price or Decimal(0)))
        add("item", item.item_number, item.description, "cost", (cost, "ITEM", item.id),
            price * qty)
    for crew in wb.crews:
        add("crew", crew.code, crew.name, "$/hr", (crews, "CREW", crew.id), crew.hourly_rate)
    e = wb.estimate
    for desc, measure, value in (("Direct cost (primary bid)", "cost", e.total_estimated_cost),
                                 ("Markup", "cost", e.markup_total),
                                 ("Bid factor", "factor", e.live_bid_factor),
                                 ("Excluded cost", "cost", e.excluded_cost)):
        add("estimate", "", desc, measure, None, value)
    for item in wb.items:
        add("bid item", item.item_number, item.description, "bid unit price",
            (bid, "ITEM_BID", item.id), item.bid_unit_price)
        add("bid item", item.item_number, item.description, "bid total",
            (bid, "ITEM_BID", item.id), item.bid_total)
    for t in display.bid_totals(wb):
        add("bid total", "", t.name, "bid total", None, t.amount)
    for a in display.scheduled(wb):
        add("schedule", a.code, a.name, "finish", None,
            Decimal((date.fromisoformat(a.finish_date) - EXCEL_EPOCH).days))
    for q in display.quantities(wb):
        el = wb.element(q.element_id)
        add("element", q.key, f"{el.name} -- {q.label}", "override",
            (cost, "ELEMENT_QTY", (q.element_id, q.key)), q.override)
    return out
