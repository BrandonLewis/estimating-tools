"""Shape a CanonicalAssemblyLibrary into a BidSheet.ai v2 template-assembly push plan.
Pure: no BidSheet.ai/Django/MCP/network. Cost-code resolution is the skill's job (it
needs the MCP); the plan carries the cost_code string.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.assemblies.model import CanonicalAssemblyLibrary

VALID_COMPONENT_TYPES = {"labor", "material", "equipment", "subcontractor", "other"}

# A component's rate_ref resolves against this rate-library kind, by component_type.
_RATE_KIND = {"labor": "labor", "equipment": "equipment", "material": "material"}


@dataclass
class AssemblyPushPlan:
    """- org_id: the organization the templates belong to
    - assemblies: [{name, assembly_type, context, context_id, description, cost_code,
      components: [create_component dicts, each with a rate_resolution {kind, key}|None],
      rate_refs: [non-routable rate_ref strings (subcontractor/other) the skill flags]}]
    """

    org_id: int = 0
    assemblies: list[dict] = field(default_factory=list)


def plan_assembly_push(library: CanonicalAssemblyLibrary, org_id: int) -> AssemblyPushPlan:
    """Field-map the library into a v2 template push plan (no live calls)."""
    assemblies: list[dict] = []
    for asm in library.assemblies:
        rate_refs: list[str] = []
        comps: list[dict] = []
        for c in asm.components:
            if c.component_type not in VALID_COMPONENT_TYPES:
                raise ValueError(
                    f"invalid component_type {c.component_type!r} "
                    f"(must be one of {sorted(VALID_COMPONENT_TYPES)})"
                )
            unit_cost = c.unit_cost if c.unit_cost is not None else 0.0
            rate_resolution = None
            if c.rate_ref:
                kind = _RATE_KIND.get(c.component_type)
                if kind is not None:
                    rate_resolution = {"kind": kind, "key": c.rate_ref}
                else:
                    # non-routable (subcontractor/other) -> can't resolve to a rate id; flag it
                    rate_refs.append(c.rate_ref)
            comps.append({
                "component_type": c.component_type,
                "name": c.name,
                "quantity": c.quantity,
                "unit": c.unit,
                "unit_cost": unit_cost,
                "trade": c.trade,
                "description": c.description,
                "rate_resolution": rate_resolution,
            })
        assemblies.append({
            "name": asm.name,
            "assembly_type": asm.assembly_type,
            "context": "template",
            "context_id": org_id,
            "description": asm.description,
            "cost_code": asm.cost_code,
            "components": comps,
            "rate_refs": rate_refs,
        })
    return AssemblyPushPlan(org_id=org_id, assemblies=assemblies)


# ---------- estimate-context load (issue #201) ----------

from estimating_tools.assemblies.load_model import CanonicalAssemblyLoad

#: BidSheet.ai labor_cost_basis values (create_component): "production" (unit_cost
#: × duration via the assembly production_rate) or "flat" (unit_cost is the
#: all-in labor cost per unit; quantity × unit_cost, no duration).
VALID_LABOR_COST_BASIS = {"production", "flat"}


@dataclass
class AssemblyLoadPlan:
    """- estimate_id: the estimate the assemblies price into
    - assemblies: [{estimate_id, estimate_item_id, bid_item_code, name,
      assembly_type, context:"estimate", context_id (== estimate_item_id),
      description, cost_code, production_rate, production_unit,
      components: [create_component dicts + labor_cost_basis + rate_resolution],
      rate_refs: [non-routable rate_ref strings the skill flags]}]
    """

    estimate_id: int = 0
    assemblies: list[dict] = field(default_factory=list)


def _component_payload(c) -> tuple[dict, str | None]:
    """Shared field-map for one component -> (create_component dict, flagged
    rate_ref | None). Enforces the two silent BidSheet.ai traps so the wrong
    encoding is unauthorable (issue #201):

    - quantity == 0 is coerced to 1.0 on write, inventing a phantom charge, so a
      $0 line cannot be stored — refuse it (omit the component instead).
    """
    if c.component_type not in VALID_COMPONENT_TYPES:
        raise ValueError(
            f"invalid component_type {c.component_type!r} "
            f"(must be one of {sorted(VALID_COMPONENT_TYPES)})"
        )
    if c.component_type == "labor" and c.labor_cost_basis not in VALID_LABOR_COST_BASIS:
        # An unknown basis (a typo like "prodution") would otherwise slip past
        # the production_rate guard below and emit a $0-labor assembly — the
        # very trap #201 exists to make unauthorable. Reject it.
        raise ValueError(
            f"component {c.name!r}: invalid labor_cost_basis "
            f"{c.labor_cost_basis!r} (must be one of "
            f"{sorted(VALID_LABOR_COST_BASIS)})"
        )
    if c.quantity == 0:
        raise ValueError(
            f"component {c.name!r}: quantity=0 is silently coerced to 1.0 by "
            "BidSheet.ai (AAR 2026-07-29 §2.1 — 'the zero became a one, inventing "
            "a charge'). A $0 placeholder cannot be stored: omit the component "
            "and note it in the assembly/item description instead."
        )
    unit_cost = c.unit_cost if c.unit_cost is not None else 0.0
    rate_resolution = None
    flagged = None
    if c.rate_ref:
        kind = _RATE_KIND.get(c.component_type)
        if kind is not None:
            rate_resolution = {"kind": kind, "key": c.rate_ref}
        else:
            flagged = c.rate_ref
    return {
        "component_type": c.component_type,
        "name": c.name,
        "quantity": c.quantity,
        "unit": c.unit,
        "unit_cost": unit_cost,
        "trade": c.trade,
        "description": c.description,
        "labor_cost_basis": c.labor_cost_basis,
        "rate_resolution": rate_resolution,
    }, flagged


def plan_assembly_load(load: CanonicalAssemblyLoad, estimate_id: int) -> AssemblyLoadPlan:
    """Field-map estimate-bound assemblies into a load plan (no live calls),
    with the roll-up contract enforced in one place.

    A production-basis labor component contributes
    ``cost = quantity × unit_cost × production_rate`` (production_rate on the
    assembly). An assembly that carries such a component with production_rate
    unset (or 0) rolls up $0 labor — the very trap that pushes people to the
    inverse encoding (hours pre-multiplied into quantity). This refuses it, so
    only the legible convention is authorable."""
    assemblies: list[dict] = []
    for item in load.items:
        for asm in item.assemblies:
            rate_refs: list[str] = []
            comps: list[dict] = []
            has_production_labor = any(
                c.component_type == "labor" and c.labor_cost_basis == "production"
                for c in asm.components
            )
            if has_production_labor and not asm.production_rate:
                raise ValueError(
                    f"assembly {asm.name!r}: carries production-basis labor but "
                    "production_rate is unset/0 — that labor rolls up $0. Set the "
                    "assembly production_rate (crew-hours); do NOT pre-multiply "
                    "hours into a component quantity."
                )
            for c in asm.components:
                payload, flagged = _component_payload(c)
                comps.append(payload)
                if flagged is not None:
                    rate_refs.append(flagged)
            assemblies.append({
                "estimate_id": estimate_id,
                "estimate_item_id": item.estimate_item_id,
                "bid_item_code": item.bid_item_code,
                "name": asm.name,
                "assembly_type": asm.assembly_type,
                "context": "estimate",
                "context_id": item.estimate_item_id,
                "description": asm.description,
                "cost_code": asm.cost_code,
                "production_rate": asm.production_rate,
                "production_unit": asm.production_unit,
                "components": comps,
                "rate_refs": rate_refs,
            })
    return AssemblyLoadPlan(estimate_id=estimate_id, assemblies=assemblies)


# ---------- render (Phase 3) ----------

from estimating_tools.artifacts import format_money, format_qty, md_table


def _dash(value) -> str:
    return "-" if value is None or value == "" else str(value)


def render_assembly_push_plan(plan: AssemblyPushPlan) -> str:
    """Render an AssemblyPushPlan as a read-only review artifact per the Phase 3 convention.

    The `## Flagged` section surfaces per-assembly `rate_refs` — non-routable rate_ref
    strings (subcontractor/other components) that fall back to inline cost at push time.
    Components whose `rate_resolution` is set are NOT flagged (that's the normal path;
    the skill resolves them at push time)."""
    assemblies_count = len(plan.assemblies)
    components_count = sum(len(a.get("components", [])) for a in plan.assemblies)
    flag_pairs = [
        (a.get("name", ""), ref)
        for a in plan.assemblies
        for ref in a.get("rate_refs", [])
    ]
    flag_count = len(flag_pairs)

    first = (
        f"{assemblies_count} assembl{'y' if assemblies_count == 1 else 'ies'}, "
        f"{components_count} component{'s' if components_count != 1 else ''}"
    )
    summary_parts = [first]
    if flag_count:
        summary_parts.append(
            f"{flag_count} non-routable rate ref{'s' if flag_count != 1 else ''}"
        )
    summary = "; ".join(summary_parts) + "."

    asm_headers = ["name", "assembly_type", "cost_code", "component_count"]
    asm_rows = [
        [
            _dash(a.get("name")),
            _dash(a.get("assembly_type")),
            _dash(a.get("cost_code")),
            str(len(a.get("components", []))),
        ]
        for a in plan.assemblies
    ]
    asm_table = md_table(asm_headers, asm_rows)

    comp_headers = ["assembly", "component_type", "name", "quantity", "unit",
                    "unit_cost", "rate_ref"]
    comp_rows: list[list[str]] = []
    for a in plan.assemblies:
        name = a.get("name", "")
        for c in a.get("components", []):
            rate_ref = "-"
            rr = c.get("rate_resolution")
            if isinstance(rr, dict) and rr.get("key"):
                rate_ref = rr["key"]
            comp_rows.append([
                _dash(name),
                _dash(c.get("component_type")),
                _dash(c.get("name")),
                format_qty(c.get("quantity")) if c.get("quantity") is not None else "-",
                _dash(c.get("unit")),
                format_money(c.get("unit_cost")) if c.get("unit_cost") is not None else "-",
                rate_ref,
            ])
    comp_table = md_table(comp_headers, comp_rows)

    out = (
        f"# Assembly push plan\n\n"
        f"{summary}\n\n"
        f"## Assemblies\n\n{asm_table}\n\n"
        f"## Components\n\n{comp_table}\n\n"
    )
    if flag_pairs:
        bullets = "\n".join(
            f"- assembly '{name}': non-routable rate_ref '{ref}'"
            for name, ref in flag_pairs
        )
        out += f"## Flagged\n\n{bullets}\n\n"
    out += "Confirm to write to BidSheet.ai."
    return out


def _rollup_cost(comp: dict, production_rate) -> float | None:
    """The BidSheet.ai roll-up for one planned component. Production-basis labor
    extends by the assembly's crew-hours (``quantity × unit_cost ×
    production_rate``); everything else is a plain ``quantity × unit_cost``.
    Returns None when a factor is missing (rendered as "-", never summed)."""
    qty = comp.get("quantity")
    unit_cost = comp.get("unit_cost")
    if qty is None or unit_cost is None:
        return None
    if comp.get("component_type") == "labor" and comp.get("labor_cost_basis") == "production":
        return qty * unit_cost * (production_rate or 0.0)
    return qty * unit_cost


def _assembly_cost(a: dict) -> float:
    pr = a.get("production_rate")
    return sum(
        c for c in (_rollup_cost(comp, pr) for comp in a.get("components", []))
        if c is not None
    )


def render_assembly_load_plan(plan: AssemblyLoadPlan) -> str:
    """Render an AssemblyLoadPlan as a read-only confirmation artifact (issue
    #201): everything about to be written to the estimate, grouped by estimate
    item, with each component's ROLLED-UP cost shown (production-basis labor:
    ``quantity × unit_cost × production_rate``; else ``quantity × unit_cost``)
    so the reviewer sees dollars, not just inputs.

    This is NOT the editable surface — the build-assemblies skill edits
    per-assembly via ``render_single``/``parse_single_with_meta``; this is the
    final "confirm to write" view over the whole load. The ``## Flagged`` section
    lists non-routable ``rate_refs`` (subcontractor/other) that fall back to
    inline ``unit_cost`` at push. The traps are already enforced by
    ``plan_assembly_load`` — a plan that reaches here cannot carry a $0-labor
    crew or a phantom-charge zero."""
    assemblies = plan.assemblies
    asm_count = len(assemblies)
    comp_count = sum(len(a.get("components", [])) for a in assemblies)
    # AssemblyLoadItem is keyed by estimate_item_id; bid_item_code is trace-only,
    # so count distinct item ids (not (id, code) pairs, which would double-count
    # one item if a hand-built load carried mismatched codes).
    item_count = len({a.get("estimate_item_id") for a in assemblies})
    flag_pairs = [
        (a.get("name", ""), ref)
        for a in assemblies for ref in a.get("rate_refs", [])
    ]
    grand_total = sum(_assembly_cost(a) for a in assemblies)

    summary_parts = [
        f"{item_count} estimate item{'s' if item_count != 1 else ''}",
        f"{asm_count} assembl{'y' if asm_count == 1 else 'ies'}",
        f"{comp_count} component{'s' if comp_count != 1 else ''}",
    ]
    summary = "; ".join(summary_parts) + f"; total {format_money(grand_total)}"
    if flag_pairs:
        summary += (
            f"; {len(flag_pairs)} non-routable rate ref"
            f"{'s' if len(flag_pairs) != 1 else ''}"
        )
    summary += "."

    def item_label(a: dict) -> str:
        code = a.get("bid_item_code")
        eid = a.get("estimate_item_id")
        return f"{eid} ({code})" if code else _dash(eid)

    asm_headers = ["item", "assembly", "assembly_type", "cost_code",
                   "production_rate", "components", "cost"]
    asm_rows = [
        [
            item_label(a),
            _dash(a.get("name")),
            _dash(a.get("assembly_type")),
            _dash(a.get("cost_code")),
            format_qty(a.get("production_rate")) if a.get("production_rate") is not None else "-",
            str(len(a.get("components", []))),
            format_money(_assembly_cost(a)),
        ]
        for a in assemblies
    ]

    comp_headers = ["item", "assembly", "component_type", "name", "quantity",
                    "unit", "unit_cost", "basis", "cost"]
    comp_rows: list[list[str]] = []
    for a in assemblies:
        pr = a.get("production_rate")
        for c in a.get("components", []):
            cost = _rollup_cost(c, pr)
            comp_rows.append([
                item_label(a),
                _dash(a.get("name")),
                _dash(c.get("component_type")),
                _dash(c.get("name")),
                format_qty(c.get("quantity")) if c.get("quantity") is not None else "-",
                _dash(c.get("unit")),
                format_money(c.get("unit_cost")) if c.get("unit_cost") is not None else "-",
                c.get("labor_cost_basis") if c.get("component_type") == "labor" else "-",
                format_money(cost) if cost is not None else "-",
            ])

    out = (
        f"# Assembly load plan\n\n"
        f"{summary}\n\n"
        f"## Assemblies\n\n{md_table(asm_headers, asm_rows)}\n\n"
        f"## Components\n\n{md_table(comp_headers, comp_rows)}\n\n"
    )
    if flag_pairs:
        bullets = "\n".join(
            f"- assembly '{name}': non-routable rate_ref '{ref}'"
            for name, ref in flag_pairs
        )
        out += f"## Flagged\n\n{bullets}\n\n"
    out += "Confirm to write to BidSheet.ai."
    return out
