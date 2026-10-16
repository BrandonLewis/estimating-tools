"""BidSheet.ai sync plan module.

`plan_sync(base_spec, edited_spec) -> SyncPlan` diffs a pre-edit spec against
an edited spec and emits rate/crew/item operation records. Pure; no MCP.
`render_sync_plan(plan) -> str` produces a read-only review artifact.

Design and rationale in
`docs/superpowers/specs/2026-07-09-bidmanager-sync-plan-design.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from estimating_tools.artifact_common import escape_string_field
from estimating_tools.artifacts import format_money, format_qty, md_table
from estimating_tools.estimate_spec._shared import _is_valid_id


@dataclass
class RateOp:
    """Create-only. LaborRate history model precludes safe updates from a
    local rate_table row alone; a follow-up phase can add effective-date-aware
    updates when we have UX to support it.
    """
    kind: Literal["create"]
    trade: str
    rate: float


@dataclass
class CrewOp:
    """Create or update. No delete — Assembly(CREW) is a library asset."""
    kind: Literal["create", "update"]
    crew_id: str
    description: str
    members: list[dict]                # {trade: str, count: int} rows; full replacement on update


@dataclass
class ItemOp:
    """Full CRUD. `estimate_item_id` is None on create; the anchor on update
    and delete. `changed_fields` on update lets the executor pick the right
    MCP tool (update_bid_item vs update_estimate_item vs both).

    wbs / cost_code / crew_id are the Phase 4.5 item metadata; "" means
    "no value" (missing spec keys normalize to "" at op construction).
    crew_id is the crew's name (= BM Assembly.name); the executor resolves
    it to a BM assembly pk at push time.
    """
    kind: Literal["create", "update", "delete"]
    estimate_item_id: int | None
    item_no: str
    description: str
    qty: float | int | str             # numOrFormula: a number, or a formula string starting with "="
    uom: str
    wbs: str = ""
    cost_code: str = ""
    crew_id: str = ""
    changed_fields: list[str] = field(default_factory=list)
    # True when this update's estimate_item_id was recovered by item_no from the
    # base snapshot (the edited spec had dropped the anchor). The executor then
    # writes the anchor back to edited_spec so later syncs don't re-run the
    # item_no heuristic — and can't degrade to warn-and-skip on a later drift. (#250)
    recovered_anchor: bool = False


_METADATA_FIELDS = ("wbs", "cost_code", "crew_id")


@dataclass
class SyncPlan:
    rate_ops: list[RateOp] = field(default_factory=list)
    crew_ops: list[CrewOp] = field(default_factory=list)
    item_ops: list[ItemOp] = field(default_factory=list)
    # Non-blocking advisories the executor should surface, never auto-apply.
    # Populated when an unanchored edited item collides by item_no with the
    # base snapshot and can be neither created (duplicate) nor updated (no
    # anchor) — see _diff_items and issue #250.
    warnings: list[str] = field(default_factory=list)


def _diff_rates(base_spec: dict, edited_spec: dict) -> list[RateOp]:
    """Emit RateOp(kind='create', ...) for every trade in edited_spec.rate_table
    that isn't in base_spec.rate_table. Preserves edited-side order. No update,
    no delete (see design doc)."""
    base_trades = {row["trade"] for row in base_spec.get("rate_table", [])}
    ops: list[RateOp] = []
    for row in edited_spec.get("rate_table", []):
        if row["trade"] not in base_trades:
            ops.append(RateOp(kind="create", trade=row["trade"], rate=row["rate"]))
    return ops


def _diff_crews(base_spec: dict, edited_spec: dict) -> list[CrewOp]:
    """Emit CrewOp(create) for every crew in edited_spec.crews with an id
    not in base_spec.crews. Emit CrewOp(update) when an existing crew's
    description or members differ. No delete — Assembly(CREW) is a library
    asset. Match key is crew.id (= BM Assembly.name).
    """
    base_by_id = {c["id"]: c for c in base_spec.get("crews", [])}
    ops: list[CrewOp] = []
    for crew in edited_spec.get("crews", []):
        base = base_by_id.get(crew["id"])
        description = crew.get("description", "")
        members = crew["members"]
        if base is None:
            ops.append(CrewOp(kind="create", crew_id=crew["id"],
                              description=description, members=members))
        elif base.get("description", "") != description or base["members"] != members:
            ops.append(CrewOp(kind="update", crew_id=crew["id"],
                              description=description, members=members))
    return ops


def _changed_fields(base: dict, edited: dict) -> list[str]:
    """Compute changed_fields for an item update op.

    Special-case for `qty`: if `edited` has no qty key (compact.py's
    `_apply_row_edits` pops it when the user clears the cell with `-`),
    treat that as "no local override" — a schema-valid state meaning BM's
    stored value should stand. Emitting a qty update in that case would
    push an arbitrary default (or the base's own value) to BM, which
    would silently corrupt the estimate.

    This mirrors the MVP no-op posture for rate updates and crew deletes:
    when the user's intent is "revert to library default," we don't push
    a diff.

    Metadata (wbs / cost_code / crew_id) is the opposite: clear-is-push.
    An absent key there means the user blanked the cell, and that's a real
    edit to sync, not "no local override."
    """
    fields = []
    for f in ("item_no", "description", "uom"):
        if base.get(f) != edited.get(f):
            fields.append(f)
    # qty: only emit if edited item has an explicit qty AND it differs from
    # base's qty. Absent qty in edited means "no local override" — no push.
    if "qty" in edited and base.get("qty") != edited["qty"]:
        fields.append("qty")
    # Metadata: clear-is-push. compact.py's _apply_row_edits pops these keys
    # when the user blanks the cell ("clear this field"), so base-set /
    # edited-absent IS a diff to push — unlike qty above, where an absent
    # key means "no local override; BM's value stands".
    for f in _METADATA_FIELDS:
        if base.get(f, "") != edited.get(f, ""):
            fields.append(f)
    return fields


def _base_item_no_index(base_items: list[dict]) -> dict[str, dict]:
    """Map item_no -> base item for reconciling UNANCHORED edited items.

    base_spec is a snapshot of the target estimate at last fetch, so a base
    row with a given item_no means that item already exists in BM — anchor or
    no anchor. When two base rows share an item_no, prefer the one that carries
    a valid estimate_item_id (that anchor is what lets us recover an update
    instead of blocking). Keyed on item_no because item_number is the estimate's
    natural key when the spec-side id anchor is missing (issue #250)."""
    index: dict[str, dict] = {}
    for it in base_items:
        no = it.get("item_no")
        if no is None:
            continue
        prev = index.get(no)
        if prev is None or (not _is_valid_id(prev.get("estimate_item_id"))
                            and _is_valid_id(it.get("estimate_item_id"))):
            index[no] = it
    return index


def _diff_items(base_spec: dict, edited_spec: dict) -> tuple[list[ItemOp], list[str]]:
    """Emit ItemOp(create/update/delete) plus non-blocking warnings.

    Primary match key is estimate_item_id (via _is_valid_id). Update ops
    include changed_fields listing which of
    item_no/description/qty/uom/wbs/cost_code/crew_id differ from base.

    An edited item with NO valid id is reconciled against the base snapshot by
    item_no BEFORE it is treated as new (issue #250): base_spec is a snapshot of
    the live estimate, so a matching item_no means the item already exists in
    BM. If the matched base row carries a valid anchor we recover it and emit an
    id-anchored update; if neither side has an anchor we can neither create
    (duplicate) nor update (no anchor), so we emit no op and warn. Only an
    unanchored edited item with no item_no match in base is a genuine create.
    """
    base_items = base_spec.get("items", [])
    base_by_id = {
        it["estimate_item_id"]: it
        for it in base_items
        if _is_valid_id(it.get("estimate_item_id"))
    }
    base_by_item_no = _base_item_no_index(base_items)
    seen_ids: set[int] = set()

    ops: list[ItemOp] = []
    warnings: list[str] = []

    def _emit_update(eid: int, base: dict, it: dict, recovered: bool = False) -> None:
        seen_ids.add(eid)
        changed = _changed_fields(base, it)
        if changed:
            ops.append(ItemOp(
                kind="update", estimate_item_id=eid,
                item_no=it["item_no"], description=it["description"],
                qty=it.get("qty", base.get("qty", 1)), uom=it["uom"],
                wbs=it.get("wbs", ""), cost_code=it.get("cost_code", ""),
                crew_id=it.get("crew_id", ""),
                changed_fields=changed,
                recovered_anchor=recovered,
            ))

    for it in edited_spec.get("items", []):
        eid = it.get("estimate_item_id")
        if _is_valid_id(eid):
            # Direct indexing (not .get) is intentional: an edited id not in
            # base means base_spec drifted between fetch and diff — surface as
            # KeyError for the caller to handle by re-fetching. See design
            # doc's error-handling section.
            _emit_update(eid, base_by_id[eid], it)
            continue

        # No id on the edited item. Before calling it new, reconcile by item_no
        # against the base snapshot so we never duplicate an item that already
        # exists in the target estimate (issue #250).
        base = base_by_item_no.get(it["item_no"])
        if base is not None:
            base_eid = base.get("estimate_item_id")
            if _is_valid_id(base_eid):
                # The edited spec dropped its anchor but the snapshot still has
                # one — recover it and diff as an id-anchored update. Flag it so
                # the executor writes the anchor back to edited_spec.
                _emit_update(base_eid, base, it, recovered=True)
            else:
                # Exists in the estimate but neither side carries an anchor:
                # can't create (would duplicate) and can't update (no anchor).
                warnings.append(
                    f"Item {it['item_no']!r} already exists in the base "
                    f"estimate snapshot but neither the edited spec nor the "
                    f"snapshot carries an estimate_item_id anchor; skipped to "
                    f"avoid creating a duplicate. Bind anchors (run a prior "
                    f"sync write-back, or fetch the estimate item ids) before "
                    f"syncing this item."
                )
            continue

        # Genuinely new — no id, and no item_no match in the estimate.
        ops.append(ItemOp(
            kind="create", estimate_item_id=None,
            item_no=it["item_no"], description=it["description"],
            qty=it.get("qty", 1), uom=it["uom"],
            wbs=it.get("wbs", ""), cost_code=it.get("cost_code", ""),
            crew_id=it.get("crew_id", ""),
        ))

    # Deletes: base items with an id not in seen_ids.
    for eid, base in base_by_id.items():
        if eid not in seen_ids:
            ops.append(ItemOp(
                kind="delete", estimate_item_id=eid,
                item_no=base["item_no"], description=base["description"],
                qty=base.get("qty", 1), uom=base["uom"],
            ))
    return ops, warnings


def plan_sync(base_spec: dict, edited_spec: dict) -> SyncPlan:
    """Diff a pre-edit spec against an edited spec and produce a BM push plan.

    base_spec: the pre-edit state (a snapshot of BM at last fetch).
    edited_spec: the parse_compact / parse_item output (or any post-edit dict).

    Returns a pure SyncPlan describing rate/crew/item deltas as operation
    records. No I/O, no MCP.
    """
    item_ops, warnings = _diff_items(base_spec, edited_spec)
    return SyncPlan(
        rate_ops=_diff_rates(base_spec, edited_spec),
        crew_ops=_diff_crews(base_spec, edited_spec),
        item_ops=item_ops,
        warnings=warnings,
    )


def _summary_line(plan: SyncPlan) -> str:
    """`N rate_op(s) · M crew_op(s) · P item_op(s).`"""
    n_rates = len(plan.rate_ops)
    n_crews = len(plan.crew_ops)
    n_items = len(plan.item_ops)
    return (
        f"{n_rates} rate_op{'s' if n_rates != 1 else ''} · "
        f"{n_crews} crew_op{'s' if n_crews != 1 else ''} · "
        f"{n_items} item_op{'s' if n_items != 1 else ''}."
    )


def _warnings_section(plan: SyncPlan) -> str:
    """A prominent, bulleted list of blocked/ambiguous items. Rendered right
    after the summary so a reviewer sees it before the op tables — a plan that
    silently dropped items would otherwise read as 'nothing to sync' (#250)."""
    bullets = "\n".join(f"- {escape_string_field(w)}" for w in plan.warnings)
    return "## Warnings\n\n" + bullets


def _rates_section(plan: SyncPlan) -> str:
    rows = [[op.trade, format_money(op.rate)] for op in plan.rate_ops]
    return "## Rates (create only)\n\n" + md_table(["trade", "rate"], rows)


def _format_qty_cell(value) -> str:
    """Render an `ItemOp.qty` for the review artifact.

    - Formula strings (`={ref:...}`) pass through unchanged — we can't
      resolve them without a workbook context, and callers reviewing the
      plan should see the formula source.
    - Numeric values route through `format_qty` for the trimmed display
      shape (`240`, `1.5`) shared with `compact.py` and the design doc's
      worked example.
    """
    if isinstance(value, str) and value.startswith("="):
        return value
    return format_qty(value)


def _crews_section(plan: SyncPlan) -> str:
    def _members_inline(members: list[dict]) -> str:
        return ", ".join(f"{m['trade']}×{m['count']}" for m in members)

    rows = [
        [op.kind, op.crew_id,
         escape_string_field(op.description) if op.description else "-",
         _members_inline(op.members)]
        for op in plan.crew_ops
    ]
    return "## Crews\n\n" + md_table(
        ["kind", "crew_id", "description", "members"], rows,
    )


def _items_section(plan: SyncPlan) -> str:
    rows = [
        [
            op.kind,
            str(op.estimate_item_id) if op.estimate_item_id is not None else "-",
            op.item_no,
            # Escape (\n, \\, control chars) so a multi-line description can't
            # break the table grammar — same convention as compact.py's cells.
            escape_string_field(op.description),
            _format_qty_cell(op.qty),
            op.uom,
            op.wbs or "-",
            op.cost_code or "-",
            op.crew_id or "-",
            "; ".join(op.changed_fields) if op.changed_fields else "-",
        ]
        for op in plan.item_ops
    ]
    return "## Items\n\n" + md_table(
        ["kind", "estimate_item_id", "item_no", "description",
         "qty", "uom", "wbs", "cost_code", "crew_id", "changed"], rows,
    )


def render_sync_plan(plan: SyncPlan) -> str:
    """Render a SyncPlan as a review artifact. Heading + summary + one section
    per sub-plan + closing confirmation. No trailing newline."""
    parts = [
        "# Sync plan",
        _summary_line(plan),
    ]
    if plan.warnings:
        parts.append(_warnings_section(plan))
    parts += [
        _rates_section(plan),
        _crews_section(plan),
        _items_section(plan),
        "Confirm to write to BidSheet.ai.",
    ]
    return "\n\n".join(parts)
