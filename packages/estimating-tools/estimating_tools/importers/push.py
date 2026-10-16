"""Map a CanonicalEstimate to a BidSheet.ai push plan (Project + Bid Schedules +
Bid Items). Pure and host-agnostic: no BidSheet.ai/Django/MCP/network.

unit_price is intentionally dropped — bid items hold structure (item_number,
item_code, description, quantity, unit, schedule), not price.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.importers.model import CanonicalEstimate


@dataclass
class PushPlan:
    """BidSheet.ai-shaped operation descriptors. Field names match the MCP tools.

    - project: {title, bid_date?}
    - schedules: [{name, display_order}]
    - templates: distinct [{item_code, description, unit}] in first-seen order
    - items: [{item_number, item_code, description, unit, estimated_quantity, schedule_name}]
    """

    project: dict = field(default_factory=dict)
    schedules: list[dict] = field(default_factory=list)
    templates: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)


def plan_push(canonical: CanonicalEstimate) -> PushPlan:
    """Field-map a CanonicalEstimate into a PushPlan (no live calls)."""
    project = {"title": canonical.project.get("name", "")}
    if canonical.project.get("bid_date"):
        project["bid_date"] = canonical.project["bid_date"]

    schedules: list[dict] = []
    templates: list[dict] = []
    seen_templates: set[tuple[str, str, str]] = set()
    items: list[dict] = []

    for order, schedule in enumerate(canonical.schedules):
        schedules.append({"name": schedule.name, "display_order": order})
        for line in schedule.items:
            code = line.item_code or ""
            key = (code, line.description, line.unit)
            if key not in seen_templates:
                seen_templates.add(key)
                templates.append({"item_code": code, "description": line.description, "unit": line.unit})
            items.append({
                "item_number": line.item_number,
                "item_code": code,
                "description": line.description,
                "unit": line.unit,
                "estimated_quantity": line.quantity,
                "schedule_name": schedule.name,
            })

    return PushPlan(project=project, schedules=schedules, templates=templates, items=items)


def diff_new_items(items: list[dict], existing_by_schedule) -> list[dict]:
    """Return items whose item_number is not already present IN THE SAME schedule.

    existing_by_schedule maps schedule_name -> set/iterable of item_numbers that
    already exist in that schedule. An item is new if its item_number is not in
    the existing set for its own schedule_name. The same item_number in a
    different schedule is kept (schedules are independent).
    """
    return [
        it for it in items
        if it["item_number"] not in set(existing_by_schedule.get(it["schedule_name"], ()))
    ]


# ---------- render (Phase 3) ----------

from estimating_tools.artifacts import format_qty, md_table


def _dash(value) -> str:
    return "-" if value is None or value == "" else str(value)


def render_push_plan(plan: PushPlan) -> str:
    """Render a PushPlan as a read-only review artifact per the Phase 3 convention."""
    schedules_count = len(plan.schedules)
    templates_count = len(plan.templates)
    items_count = len(plan.items)
    summary = (
        f"{schedules_count} schedule{'s' if schedules_count != 1 else ''}, "
        f"{templates_count} template{'s' if templates_count != 1 else ''}, "
        f"{items_count} item{'s' if items_count != 1 else ''}."
    )

    # Project: single-row key-value table
    project_headers = ["Project title", "Bid date"]
    project_row = [
        _dash(plan.project.get("title", "")),
        _dash(plan.project.get("bid_date", "")),
    ]
    project_table = md_table(project_headers, [project_row])

    schedules_headers = ["name", "display_order"]
    schedules_rows = [[_dash(s.get("name")), _dash(s.get("display_order"))] for s in plan.schedules]
    schedules_table = md_table(schedules_headers, schedules_rows)

    templates_headers = ["item_code", "description", "unit"]
    templates_rows = [
        [_dash(t.get("item_code")), _dash(t.get("description")), _dash(t.get("unit"))]
        for t in plan.templates
    ]
    templates_table = md_table(templates_headers, templates_rows)

    items_headers = ["item_number", "item_code", "description", "unit",
                     "estimated_quantity", "schedule_name"]
    items_rows = [
        [
            _dash(it.get("item_number")),
            _dash(it.get("item_code")),
            _dash(it.get("description")),
            _dash(it.get("unit")),
            format_qty(it.get("estimated_quantity")) if it.get("estimated_quantity") is not None else "-",
            _dash(it.get("schedule_name")),
        ]
        for it in plan.items
    ]
    items_table = md_table(items_headers, items_rows)

    return (
        f"# Push plan\n\n"
        f"{summary}\n\n"
        f"## Project\n\n{project_table}\n\n"
        f"## Schedules\n\n{schedules_table}\n\n"
        f"## Templates\n\n{templates_table}\n\n"
        f"## Items\n\n{items_table}\n\n"
        f"Confirm to write to BidSheet.ai."
    )
