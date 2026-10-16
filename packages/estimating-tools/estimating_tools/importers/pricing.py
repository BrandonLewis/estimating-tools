"""Map a CanonicalEstimate to a BidSheet.ai estimate-pricing plan. Pure and
host-agnostic: no BidSheet.ai/Django/MCP/network.

Only line items that carry a unit_price are priced; null-price items are omitted
(priced later by hand or by quotes). Each priced item carries a default
confidence and a provenance note, plus its schedule_name so the skill can
resolve on (schedule_name, item_number) — the same pairing used by push-estimate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.importers.model import CanonicalEstimate


@dataclass
class PricingPlan:
    """Estimate-level pricing descriptors (pre-resolution — NOT direct
    create_estimate_item kwargs).

    - estimate_name: the find-or-create name for the Estimate
    - items: [{schedule_name, item_number, unit_price, confidence_level, notes}]
      for priced items. `schedule_name`/`item_number` are LOOKUP keys: the
      price-estimate skill resolves (schedule_name, item_number) ->
      project_bid_item_id (via list_bid_items) before the MCP call — mirroring
      push-estimate's per-schedule handling to avoid collisions when the same
      item_number appears in multiple schedules. The remaining fields
      (unit_price, confidence_level, notes) pass through to create_estimate_item.
    """

    estimate_name: str = ""
    items: list[dict] = field(default_factory=list)


def plan_pricing(canonical: CanonicalEstimate, source: str | None = None) -> PricingPlan:
    """Field-map a CanonicalEstimate into a PricingPlan (no live calls).

    `source` defaults to canonical.project["source"]; when present it drives the
    per-item provenance note `imported from {source}`, else notes are blank.

    Each emitted item carries `schedule_name` (the Schedule it came from) so
    the price-estimate skill can build a (schedule_name, item_number) map and
    avoid collisions across schedules that share item numbers.
    """
    name = canonical.project.get("name", "")
    estimate_name = f"{name} — Imported Estimate"

    src = source if source is not None else canonical.project.get("source")
    notes = f"imported from {src}" if src else ""

    items: list[dict] = []
    for schedule in canonical.schedules:
        for line in schedule.items:
            if line.unit_price is None:
                continue
            items.append({
                "schedule_name": schedule.name,
                "item_number": line.item_number,
                "unit_price": line.unit_price,
                "confidence_level": "medium",
                "notes": notes,
            })

    return PricingPlan(estimate_name=estimate_name, items=items)


# ---------- render (Phase 3) ----------

from estimating_tools.artifacts import format_money, md_table


def _dash(value) -> str:
    return "-" if value is None or value == "" else str(value)


def render_pricing_plan(plan: PricingPlan) -> str:
    """Render a PricingPlan as a read-only review artifact per the Phase 3 convention."""
    n = len(plan.items)
    summary = f"{n} item{'s' if n != 1 else ''} to price."

    estimate_table = md_table(["Estimate name"], [[_dash(plan.estimate_name)]])

    items_headers = ["schedule_name", "item_number", "unit_price", "confidence_level", "notes"]
    items_rows = [
        [
            _dash(it.get("schedule_name")),
            _dash(it.get("item_number")),
            format_money(it.get("unit_price")) if it.get("unit_price") is not None else "-",
            _dash(it.get("confidence_level")),
            _dash(it.get("notes")),
        ]
        for it in plan.items
    ]
    items_table = md_table(items_headers, items_rows)

    return (
        f"# Pricing plan\n\n"
        f"{summary}\n\n"
        f"## Estimate\n\n{estimate_table}\n\n"
        f"## Priced items\n\n{items_table}\n\n"
        f"Confirm to write to BidSheet.ai."
    )
