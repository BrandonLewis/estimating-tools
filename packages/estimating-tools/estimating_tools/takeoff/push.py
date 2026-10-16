"""Plan a takeoff push into BidSheet.ai, and guard assembly ownership.
Pure: no BidSheet.ai/Django/MCP/network. The skill executes the plan's actions.

Takeoff pushes target the ESTIMATE layer, never bid-item quantities:
`ProjectBidItem.quantity` is the OFFICIAL agency schedule quantity — writing
takeoff quantities there corrupted a live bid schedule (BidManager #984,
2026-08). The default target ("estimate-structures") plans
create_structure/add_structure_section calls whose section dimensions (FEET)
drive the Structures grid's CY computation, plus a read-only advisory check of
model quantity vs the official schedule. The legacy bid-item-quantity writer
survives only as target="bid-item-quantities" and stamps a WARNING into its
plan; it is forbidden on live bids.

Clone-not-mutate: the org template library is read-only; only assemblies cloned
onto the current estimate item may be written. `assert_estimate_owned` is the guard
the skill calls before every assembly/component mutation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.takeoff.model import CanonicalTakeoff


class OwnershipError(Exception):
    """A write would target an assembly not owned by the current estimate item."""


def is_estimate_owned(assembly: dict, estimate_item_id: int) -> bool:
    """True iff `assembly` (a get_assembly/clone detail dict) belongs to THIS estimate
    item. Template-library and other-estimate assemblies return False."""
    return (
        assembly.get("context") == "estimate"
        and assembly.get("context_id") == estimate_item_id
    )


def assert_estimate_owned(assembly: dict, estimate_item_id: int) -> None:
    """Raise OwnershipError unless `assembly` is owned by `estimate_item_id`."""
    if not is_estimate_owned(assembly, estimate_item_id):
        raise OwnershipError(
            f"refusing to mutate assembly {assembly.get('id')!r} "
            f"(context={assembly.get('context')!r}, context_id={assembly.get('context_id')!r}); "
            f"only estimate-item {estimate_item_id} assemblies may be written "
            f"(template-library assemblies are read-only)"
        )


VALID_TARGETS = ("estimate-structures", "bid-item-quantities")

# Stamped into every legacy bid-item-quantity plan. Loud on purpose.
LEGACY_TARGET_WARNING = ("writes OFFICIAL agency schedule quantities — "
                         "forbidden on live bids; see BM #984")


@dataclass
class TakeoffPushPlan:
    """LEGACY (target="bid-item-quantities") action lists — writes bid-item
    quantities, i.e. the OFFICIAL agency schedule. Forbidden on live bids
    (BM #984); every instance carries the WARNING.

    - quantity_updates: existing bid items to re-drive
      [{project_bid_item_id, item_number, schedule, estimated_quantity}]
    - quantity_creates: new bid items
      [{item_number, item_code, description, unit, estimated_quantity, schedule}]
    - unresolved: quantity rows that can neither match nor create [{description, kind, reason}]
    - unsupported: material/structure rows (later phases) [{description, kind}]
    """

    quantity_updates: list = field(default_factory=list)
    quantity_creates: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)
    WARNING: str = LEGACY_TARGET_WARNING


@dataclass
class StructuresPushPlan:
    """Default (target="estimate-structures") plan: takeoff quantities land on
    the ESTIMATE layer as structures, never on official bid-item quantities.

    - structure_plans: one per quantity row that has structural-SOLID
      elements (issue #215: reinforcement / fasteners / joint seals /
      length-paid barriers / counts / lump sums are filtered out and ride
      the advisory check only) —
      [{item_number, schedule, structure_id, sections: [{section_type,
        custom_name, dimensions: {length, width, height} (FEET) plus an
        optional signed `cy` / `volume_factor` (#210), allow_duplicate}]}].
        The skill executes them via create_structure
      (first sections batch) / add_structure_section (appends).
    - advisory_quantity_check: read-only comparison rows
      [{item_number, schedule, model_qty, unit}] — surface model vs official
      schedule quantity deltas to the estimator; NEVER written to BidSheet.ai.
    - unresolved: quantity rows without elements [{description, kind, reason}]
    - unsupported: material/structure rows (later phases) [{description, kind}]
    """

    structure_plans: list = field(default_factory=list)
    advisory_quantity_check: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)


def _match_existing(row, existing: list[dict]):
    """Find an existing bid item matching `row` within the same schedule.

    Schedule must match exactly (a row with schedule=None matches only items
    whose schedule is None). `item_number` is authoritative: when the row has one,
    it matches only by item_number — a miss means the item is new, never a
    cost_code fall-back to a different item. A row without an item_number matches
    by cost_code only when exactly one item in the schedule carries that code (an
    ambiguous, non-unique code is left unmatched). Returns the existing dict or
    None."""
    same_schedule = [e for e in existing if e.get("schedule") == row.schedule]
    if row.item_number:
        for e in same_schedule:
            if e.get("item_number") == row.item_number:
                return e
        return None
    if row.cost_code:
        matches = [e for e in same_schedule if e.get("cost_code") == row.cost_code]
        if len(matches) == 1:
            return matches[0]
    return None


def plan_takeoff_push(
    takeoff: CanonicalTakeoff,
    existing_bid_items: list[dict] | None = None,
    target: str = "estimate-structures",
    structure_id: str | None = None,
) -> "StructuresPushPlan | TakeoffPushPlan":
    """Pure: plan a takeoff push for the given target.

    target="estimate-structures" (default): each quantity row's `elements`
    become structure sections on the estimate (StructuresPushPlan); quantities
    are only ever an advisory check. Each section's structure id is the row's
    own `structure_id` when set, else the caller's `structure_id`
    (est-takeoff plan --structure-id), else the takeoff's project_ref — so one
    takeoff can span several distinct physical structures (issue #211).

    target="bid-item-quantities" (LEGACY): the old bid-item quantity
    updates/creates split. It writes the OFFICIAL agency schedule quantity and
    is forbidden on live bids (BM #984) — the plan carries a WARNING.

    Material and structure rows are collected into `unsupported` for both
    targets; nothing is dropped.
    """
    if target not in VALID_TARGETS:
        raise ValueError(f"invalid target {target!r} (expected one of {list(VALID_TARGETS)})")
    if target == "estimate-structures":
        return _plan_structures(takeoff, structure_id)
    return _plan_bid_item_quantities(takeoff, existing_bid_items)


# Which takeoff elements become structure SECTIONS (issue #215).
#
# The estimate-structures layer models poured/placed SOLIDS whose volume rolls
# up to a CY (or, for a driven/furnished shaft, a running length). Everything
# else on a takeoff — reinforcement and rail by weight, dowels and joint seals
# and length-paid barriers by length, girders and driven piles by count,
# lump-sum removals — is a pay quantity, not a section. Sectioning it floods
# the CY grid with dimensionless noise: one real bridge takeoff planned 1,806
# rebar "sections" (+ 235 dowels, ...), 2,137 in all, against ~38 actual solids.
#
# The discriminant is the element's IFC-derived `measure`, which keeps this
# org-agnostic — no cost-code or item-number coupling. A volumetric measure is
# always a section; a linear measure is a section only for a genuinely linear
# STRUCTURAL member (a pile shaft), never for a length-paid attachment (barrier,
# joint seal, rail). Count and weight measures are never sections. An element
# carrying NO `measure` (takeoffs before est-bim 0.1.32) is treated as a solid,
# preserving the pre-filter behaviour so older takeoffs still plan every section.
_VOLUME_MEASURES = frozenset({"GrossVolume", "NetVolume", "Volume"})
_LINEAR_SECTION_TYPES = frozenset({"pile"})


def _section_dimensions(el: dict) -> dict:
    """The `dimensions` for one element's section.

    The box keys (FEET) always ride. An explicit `cy` (SIGNED — deducts
    allowed) and/or a `volume_factor` (e.g. 0.5 for a triangular wedge) ride
    only when the producer set them, matching what create_structure /
    add_structure_section already accept (issue #210): BidSheet.ai takes an
    explicit `cy` as the section's cubic yards, else computes
    length × width × height × volume_factor / 27. Absent → box-only, exactly
    as before, so older takeoffs are unaffected."""
    dims = {
        "length": el.get("length_ft"),
        "width": el.get("width_ft"),
        "height": el.get("height_ft"),
    }
    cy = el.get("cy")
    if cy is not None:
        dims["cy"] = cy            # signed — a deduct is an honest negative CY
    volume_factor = el.get("volume_factor")
    if volume_factor is not None:
        dims["volume_factor"] = volume_factor
    return dims


def _element_is_section(el: dict) -> bool:
    """True iff `el` is a structural solid that should become a structure
    section, rather than a pay quantity that only rides the advisory check."""
    measure = el.get("measure")
    if measure is None:                       # legacy takeoff — section as before
        return True
    if measure in _VOLUME_MEASURES:
        return True
    if measure == "Length" and (el.get("section_type") or "") in _LINEAR_SECTION_TYPES:
        return True
    return False


def _plan_structures(takeoff: CanonicalTakeoff, structure_id: str | None) -> StructuresPushPlan:
    # A takeoff can span multiple physical structures on distinct bid items;
    # each row may name its own via TakeoffRow.structure_id, falling back to the
    # caller's --structure-id then the takeoff's project_ref (issue #211). The
    # fallback is only REQUIRED for rows that don't carry their own id.
    fallback = structure_id or takeoff.project_ref
    if not fallback and any(
        row.kind == "quantity" and not row.structure_id for row in takeoff.rows
    ):
        raise ValueError(
            "the estimate-structures target needs a structure id: pass "
            "--structure-id (structure_id=), set the takeoff's project_ref, or "
            "give every quantity row its own structure_id")
    plan = StructuresPushPlan()
    planned_gids: set[str] = set()
    for row in takeoff.rows:
        if row.kind != "quantity":
            plan.unsupported.append({"description": row.description, "kind": row.kind})
            continue
        plan.advisory_quantity_check.append({
            "item_number": row.item_number,
            "schedule": row.schedule,
            "model_qty": row.quantity,
            "unit": row.unit,
        })
        raw = list(row.elements or [])
        if not raw:
            plan.unresolved.append({
                "description": row.description,
                "kind": row.kind,
                "reason": "no elements on the row — regenerate the takeoff with "
                          "est-bim >= 0.1.11 (or add elements) to plan structure sections",
            })
            continue
        # Only structural SOLIDS become sections; reinforcement, fasteners,
        # joint seals, length-paid barriers/rails, counts and lump sums ride as
        # the advisory pay quantity (recorded above) with no section (#215).
        solids = [el for el in raw if _element_is_section(el)]
        if not solids:
            # a pay-only row (e.g. rebar by weight) — nothing to section; its
            # quantity is already in advisory_quantity_check
            continue
        # a multi-classified element (issue #106: furnish + drive on one
        # pile) rides several pay-item rows, but it is ONE physical section —
        # plan it under its first row only. Identity is global_id; gid-less
        # legacy entries never dedupe (distinct walls can share a name).
        # Dedupe among the SOLIDS only, so a pay-only row can never claim a
        # physical element's global_id ahead of the solid row that sections it.
        elements = []
        for el in solids:
            gid = el.get("global_id")
            if gid and gid in planned_gids:
                continue
            if gid:
                planned_gids.add(gid)
            elements.append(el)
        if not elements:
            # every physical element already planned under another pay item;
            # this row's quantity remains in advisory_quantity_check
            continue
        sections = []
        seen_types: set[str] = set()
        for el in elements:
            stype = el.get("section_type") or "other"
            for _ in range(max(int(el.get("count") or 1), 1)):
                sections.append({
                    "section_type": stype,
                    "custom_name": el.get("name"),
                    # lowercase keys, FEET — drive the Structures grid's CY math;
                    # plus a signed cy / volume_factor when the element carries
                    # them (issue #210)
                    "dimensions": _section_dimensions(el),
                    "allow_duplicate": stype in seen_types,
                })
                seen_types.add(stype)
        plan.structure_plans.append({
            "item_number": row.item_number,
            "schedule": row.schedule,
            "structure_id": row.structure_id or fallback,   # per-row (#211)
            "sections": sections,
        })
    return plan


def _plan_bid_item_quantities(
    takeoff: CanonicalTakeoff, existing_bid_items: list[dict] | None
) -> TakeoffPushPlan:
    """LEGACY: split takeoff rows into bid-item quantity updates/creates."""
    existing = list(existing_bid_items or [])
    plan = TakeoffPushPlan()
    for row in takeoff.rows:
        if row.kind != "quantity":
            plan.unsupported.append({"description": row.description, "kind": row.kind})
            continue
        match = _match_existing(row, existing)
        if match is not None:
            plan.quantity_updates.append({
                "project_bid_item_id": match.get("project_bid_item_id"),
                "item_number": match.get("item_number"),
                "schedule": match.get("schedule"),
                "estimated_quantity": row.quantity,
            })
        elif row.item_number:
            plan.quantity_creates.append({
                "item_number": row.item_number,
                "item_code": row.cost_code or "",
                "description": row.description,
                "unit": row.unit,
                "estimated_quantity": row.quantity,
                "schedule": row.schedule,
            })
        else:
            plan.unresolved.append({
                "description": row.description,
                "kind": row.kind,
                "reason": "no item_number to match an existing bid item or create a new one",
            })
    return plan


# ---------- render (Phase 3) ----------

from estimating_tools.artifacts import format_qty, md_table


def _dash(value) -> str:
    return "-" if value is None or value == "" else str(value)


def render_takeoff_push_plan(plan: TakeoffPushPlan) -> str:
    """Render a LEGACY TakeoffPushPlan as a read-only review artifact per the
    Phase 3 convention. The plan's WARNING (official-schedule write; BM #984)
    leads the render.

    unresolved / unsupported are top-level sections (not '## Flagged' bullets) because
    they represent structured rows the user must review, not incidental warnings."""
    matched_count = len(plan.quantity_updates)
    created_count = len(plan.quantity_creates)
    unresolved_count = len(plan.unresolved)
    unsupported_count = len(plan.unsupported)
    summary = (
        f"{matched_count} matched, {created_count} created, "
        f"{unresolved_count} unresolved, {unsupported_count} unsupported."
    )

    matched_headers = ["project_bid_item_id", "item_number", "schedule", "estimated_quantity"]
    matched_rows = [
        [
            _dash(r.get("project_bid_item_id")),
            _dash(r.get("item_number")),
            _dash(r.get("schedule")),
            format_qty(r.get("estimated_quantity")) if r.get("estimated_quantity") is not None else "-",
        ]
        for r in plan.quantity_updates
    ]
    matched_table = md_table(matched_headers, matched_rows)

    created_headers = ["item_number", "item_code", "description", "unit",
                       "estimated_quantity", "schedule"]
    created_rows = [
        [
            _dash(r.get("item_number")),
            _dash(r.get("item_code")),
            _dash(r.get("description")),
            _dash(r.get("unit")),
            format_qty(r.get("estimated_quantity")) if r.get("estimated_quantity") is not None else "-",
            _dash(r.get("schedule")),
        ]
        for r in plan.quantity_creates
    ]
    created_table = md_table(created_headers, created_rows)

    unresolved_headers = ["description", "kind", "reason"]
    unresolved_rows = [
        [_dash(r.get("description")), _dash(r.get("kind")), _dash(r.get("reason"))]
        for r in plan.unresolved
    ]
    unresolved_table = md_table(unresolved_headers, unresolved_rows)

    unsupported_headers = ["description", "kind"]
    unsupported_rows = [
        [_dash(r.get("description")), _dash(r.get("kind"))]
        for r in plan.unsupported
    ]
    unsupported_table = md_table(unsupported_headers, unsupported_rows)

    return (
        f"# Takeoff push plan\n\n"
        f"**WARNING:** {plan.WARNING}\n\n"
        f"{summary}\n\n"
        f"## Matched\n\n{matched_table}\n\n"
        f"## Created\n\n{created_table}\n\n"
        f"## Unresolved\n\n{unresolved_table}\n\n"
        f"## Unsupported\n\n{unsupported_table}\n\n"
        f"Confirm to write to BidSheet.ai."
    )
