"""Tests for the BidSheet.ai sync plan (estimate_spec/sync.py).

`plan_sync(base_spec, edited_spec) -> SyncPlan` diffs a pre-edit spec against
an edited spec and emits rate/crew/item operation records. Pure; no MCP.
Design in docs/superpowers/specs/2026-07-09-bidmanager-sync-plan-design.md.
"""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.sync import (
    CrewOp,
    ItemOp,
    RateOp,
    SyncPlan,
    plan_sync,
)


def _spec(items=None, rate_table=None, crews=None, project="Sample"):
    """Minimal well-formed spec. Callers supply items / rate_table / crews."""
    return {
        "project": project,
        "markup": 100,
        "rate_table": rate_table if rate_table is not None
                      else [{"trade": "FORE", "rate": 150}],
        "crews": crews if crews is not None else [],
        "items": items if items is not None else [],
    }


def test_sync_plan_default_is_empty():
    plan = SyncPlan()
    assert plan.rate_ops == []
    assert plan.crew_ops == []
    assert plan.item_ops == []


def test_rate_op_holds_kind_trade_and_rate():
    op = RateOp(kind="create", trade="LAB", rate=95.0)
    assert op.kind == "create"
    assert op.trade == "LAB"
    assert op.rate == 95.0


def test_crew_op_holds_kind_id_description_and_members():
    op = CrewOp(kind="create", crew_id="crew_lab_2",
                description="2-person lab crew",
                members=[{"trade": "LAB", "count": 2}])
    assert op.kind == "create"
    assert op.crew_id == "crew_lab_2"
    assert op.description == "2-person lab crew"
    assert op.members == [{"trade": "LAB", "count": 2}]


def test_item_op_holds_kind_id_and_fields():
    op = ItemOp(kind="update", estimate_item_id=100,
                item_no="Item # 1", description="Mob",
                qty=1, uom="LS", changed_fields=["qty"])
    assert op.kind == "update"
    assert op.estimate_item_id == 100
    assert op.item_no == "Item # 1"
    assert op.changed_fields == ["qty"]


def test_item_op_changed_fields_defaults_to_empty_list():
    op = ItemOp(kind="create", estimate_item_id=None,
                item_no="Item # 99", description="New",
                qty=1, uom="LS")
    assert op.changed_fields == []


def test_plan_sync_no_op_returns_empty_plan():
    """An unchanged spec (base == edited) produces an empty plan."""
    spec = _spec()
    plan = plan_sync(spec, spec)
    assert plan == SyncPlan()


def test_plan_sync_empty_top_level_arrays_returns_empty_plan():
    """rate_table=[], crews=[], items=[] on both sides → empty plan."""
    spec = _spec(items=[], rate_table=[], crews=[])
    plan = plan_sync(spec, spec)
    assert plan == SyncPlan()


# ---- Rate diff -------------------------------------------------------------

def test_plan_sync_new_trade_creates_rate_op():
    base = _spec(rate_table=[{"trade": "FORE", "rate": 150}])
    edited = _spec(rate_table=[
        {"trade": "FORE", "rate": 150},
        {"trade": "LAB", "rate": 95},
    ])
    plan = plan_sync(base, edited)
    assert plan.rate_ops == [RateOp(kind="create", trade="LAB", rate=95)]


def test_plan_sync_multiple_new_trades_preserve_edited_order():
    base = _spec(rate_table=[{"trade": "FORE", "rate": 150}])
    edited = _spec(rate_table=[
        {"trade": "FORE", "rate": 150},
        {"trade": "LAB", "rate": 95},
        {"trade": "OPER", "rate": 145},
    ])
    plan = plan_sync(base, edited)
    assert [op.trade for op in plan.rate_ops] == ["LAB", "OPER"]


def test_plan_sync_trade_in_base_absent_from_edited_no_op():
    """No delete for rates — LaborRate is a library asset with history."""
    base = _spec(rate_table=[
        {"trade": "FORE", "rate": 150},
        {"trade": "LAB", "rate": 95},
    ])
    edited = _spec(rate_table=[{"trade": "FORE", "rate": 150}])
    plan = plan_sync(base, edited)
    assert plan.rate_ops == []


def test_plan_sync_trade_rate_changed_no_update_op():
    """MVP skips rate updates. A change would require a new LaborRate row
    with a fresh effective_date — out of scope."""
    base = _spec(rate_table=[{"trade": "FORE", "rate": 150}])
    edited = _spec(rate_table=[{"trade": "FORE", "rate": 175}])
    plan = plan_sync(base, edited)
    assert plan.rate_ops == []


# ---- Crew diff -------------------------------------------------------------

def _crew(crew_id, description="", members=None):
    return {"id": crew_id, "description": description,
            "members": members or [{"trade": "LAB", "count": 1}]}


def test_plan_sync_new_crew_creates_crew_op():
    base = _spec(crews=[])
    edited = _spec(crews=[_crew("crew_lab_2",
                                description="2-person lab crew",
                                members=[{"trade": "LAB", "count": 2}])])
    plan = plan_sync(base, edited)
    assert plan.crew_ops == [
        CrewOp(kind="create", crew_id="crew_lab_2",
               description="2-person lab crew",
               members=[{"trade": "LAB", "count": 2}]),
    ]


def test_plan_sync_crew_member_added_updates_crew_op():
    base = _spec(crews=[_crew("crew_x", members=[{"trade": "LAB", "count": 1}])])
    edited = _spec(crews=[_crew("crew_x", members=[
        {"trade": "LAB", "count": 1},
        {"trade": "FORE", "count": 1},
    ])])
    plan = plan_sync(base, edited)
    assert plan.crew_ops == [
        CrewOp(kind="update", crew_id="crew_x", description="",
               members=[{"trade": "LAB", "count": 1},
                        {"trade": "FORE", "count": 1}]),
    ]


def test_plan_sync_crew_description_changed_updates_crew_op():
    base = _spec(crews=[_crew("crew_x", description="Old")])
    edited = _spec(crews=[_crew("crew_x", description="New")])
    plan = plan_sync(base, edited)
    assert len(plan.crew_ops) == 1
    assert plan.crew_ops[0].kind == "update"
    assert plan.crew_ops[0].description == "New"


def test_plan_sync_crew_unchanged_no_op():
    crew = _crew("crew_x", description="Steady",
                 members=[{"trade": "LAB", "count": 2}])
    base = _spec(crews=[crew])
    edited = _spec(crews=[dict(crew)])                        # shallow copy
    plan = plan_sync(base, edited)
    assert plan.crew_ops == []


def test_plan_sync_crew_in_base_absent_from_edited_no_op():
    """No delete for crews — Assembly(CREW) is a library asset."""
    base = _spec(crews=[_crew("crew_x")])
    edited = _spec(crews=[])
    plan = plan_sync(base, edited)
    assert plan.crew_ops == []


# ---- Item diff -------------------------------------------------------------

def _item(item_no, description="Task", qty=1, uom="LS", **overrides):
    """Minimal item dict for diff tests."""
    base = {"item_no": item_no, "recipe": "mob_item", "sheet": item_no,
            "description": description, "qty": qty, "uom": uom, "labor": []}
    base.update(overrides)
    return base


def _synced(estimate_item_id, item_no, **overrides):
    return _item(item_no, estimate_item_id=estimate_item_id, **overrides)


def test_plan_sync_new_item_no_id_creates_item_op():
    base = _spec(items=[])
    edited = _spec(items=[_item("Item # 1", description="Mob", qty=1, uom="LS")])
    plan = plan_sync(base, edited)
    assert plan.item_ops == [
        ItemOp(kind="create", estimate_item_id=None,
               item_no="Item # 1", description="Mob",
               qty=1, uom="LS"),
    ]


def test_plan_sync_edit_qty_on_synced_item_updates_with_changed_field():
    base = _spec(items=[_synced(100, "Item # 1", qty=1)])
    edited = _spec(items=[_synced(100, "Item # 1", qty=240)])
    plan = plan_sync(base, edited)
    assert plan.item_ops == [
        ItemOp(kind="update", estimate_item_id=100,
               item_no="Item # 1", description="Task",
               qty=240, uom="LS", changed_fields=["qty"]),
    ]


def test_plan_sync_rename_item_no_on_synced_item_updates_with_changed_field():
    base = _spec(items=[_synced(100, "Item # 1")])
    edited = _spec(items=[_synced(100, "Item # 1A")])
    plan = plan_sync(base, edited)
    assert plan.item_ops == [
        ItemOp(kind="update", estimate_item_id=100,
               item_no="Item # 1A", description="Task",
               qty=1, uom="LS", changed_fields=["item_no"]),
    ]


def test_plan_sync_edit_two_fields_emits_both_in_changed_fields():
    base = _spec(items=[_synced(100, "Item # 1", qty=1)])
    edited = _spec(items=[_synced(100, "Item # 1A", qty=240)])
    plan = plan_sync(base, edited)
    assert len(plan.item_ops) == 1
    op = plan.item_ops[0]
    assert op.kind == "update"
    assert set(op.changed_fields) == {"item_no", "qty"}


def test_plan_sync_delete_synced_item_omitted_from_edited():
    base = _spec(items=[
        _synced(100, "Item # 1"),
        _synced(200, "Item # 2"),
    ])
    edited = _spec(items=[_synced(100, "Item # 1")])
    plan = plan_sync(base, edited)
    assert plan.item_ops == [
        ItemOp(kind="delete", estimate_item_id=200,
               item_no="Item # 2", description="Task",
               qty=1, uom="LS"),
    ]


def test_plan_sync_reorder_items_no_op():
    """Identity is by estimate_item_id, not position — reordering alone is a no-op."""
    base = _spec(items=[
        _synced(100, "Item # 1"),
        _synced(200, "Item # 2"),
    ])
    edited = _spec(items=[
        _synced(200, "Item # 2"),
        _synced(100, "Item # 1"),
    ])
    plan = plan_sync(base, edited)
    assert plan.item_ops == []


def test_plan_sync_unchanged_synced_item_no_op():
    base = _spec(items=[_synced(100, "Item # 1", qty=5, uom="EA")])
    edited = _spec(items=[_synced(100, "Item # 1", qty=5, uom="EA")])
    plan = plan_sync(base, edited)
    assert plan.item_ops == []


def test_plan_sync_create_and_update_together():
    """Combined: existing synced item edited + new (unsynced) item added."""
    base = _spec(items=[_synced(100, "Item # 1", qty=1)])
    edited = _spec(items=[
        _synced(100, "Item # 1", qty=240),
        _item("Item # 99", description="Punchlist", qty=1, uom="LS"),
    ])
    plan = plan_sync(base, edited)
    assert len(plan.item_ops) == 2
    kinds = sorted(op.kind for op in plan.item_ops)
    assert kinds == ["create", "update"]


def test_plan_sync_qty_popped_by_compact_edit_no_op():
    """When a user clears the qty cell in the compact view (compact.py
    pops the key), _diff_items must NOT emit a qty update — that would
    silently push a default value to BM and corrupt the estimate. The
    correct MVP behavior is to treat "qty absent in edited" as "no local
    override" (BM's stored value stands unchanged).
    """
    base = _spec(items=[_synced(100, "Item # 1", qty=5, uom="EA")])
    edited_item = _synced(100, "Item # 1", uom="EA")
    edited_item.pop("qty", None)                              # simulate compact's `-` edit
    edited = _spec(items=[edited_item])
    plan = plan_sync(base, edited)
    # No update op emitted: the cleared qty doesn't produce a diff.
    assert plan.item_ops == []


def test_plan_sync_qty_popped_still_no_op_when_other_fields_change():
    """A popped qty + another edit still emits an update — but changed_fields
    only includes the other edit, not qty."""
    base = _spec(items=[_synced(100, "Item # 1", qty=5, uom="EA",
                                description="Old")])
    edited_item = _synced(100, "Item # 1", uom="EA", description="New")
    edited_item.pop("qty", None)
    edited = _spec(items=[edited_item])
    plan = plan_sync(base, edited)
    assert len(plan.item_ops) == 1
    op = plan.item_ops[0]
    assert op.kind == "update"
    assert op.changed_fields == ["description"]
    # qty on the op carries the base value so downstream code has a stable
    # numeric to work with (no None sentinel):
    assert op.qty == 5


# ---------- item metadata (wbs / cost_code / crew_id) ----------

def test_item_op_metadata_defaults_to_empty_strings():
    op = ItemOp(kind="create", estimate_item_id=None,
                item_no="Item # 99", description="New",
                qty=1, uom="LS")
    assert op.wbs == ""
    assert op.cost_code == ""
    assert op.crew_id == ""


def test_plan_sync_metadata_added_emits_update_with_value():
    base = _spec(items=[_synced(100, "Item # 1")])
    edited = _spec(items=[_synced(100, "Item # 1", wbs="1.2.3")])
    plan = plan_sync(base, edited)
    assert len(plan.item_ops) == 1
    op = plan.item_ops[0]
    assert op.kind == "update"
    assert op.changed_fields == ["wbs"]
    assert op.wbs == "1.2.3"


def test_plan_sync_metadata_cleared_emits_update_with_empty_value():
    """Clear-is-push: compact.py pops the key when the user blanks the cell,
    and that clear is a real edit to sync (unlike qty's no-override rule)."""
    base = _spec(items=[_synced(100, "Item # 1",
                                cost_code="02-110", crew_id="crew_lab_2")])
    edited = _spec(items=[_synced(100, "Item # 1")])
    plan = plan_sync(base, edited)
    assert len(plan.item_ops) == 1
    op = plan.item_ops[0]
    assert op.changed_fields == ["cost_code", "crew_id"]
    assert op.cost_code == ""
    assert op.crew_id == ""


def test_plan_sync_metadata_absent_in_both_no_op():
    base = _spec(items=[_synced(100, "Item # 1")])
    edited = _spec(items=[_synced(100, "Item # 1")])
    assert plan_sync(base, edited) == SyncPlan()


def test_plan_sync_metadata_empty_string_vs_absent_no_op():
    """Empty string and a missing key both normalize to "no value" — not a diff."""
    base = _spec(items=[_synced(100, "Item # 1", wbs="")])
    edited = _spec(items=[_synced(100, "Item # 1")])
    assert plan_sync(base, edited) == SyncPlan()


def test_plan_sync_create_carries_metadata():
    base = _spec(items=[])
    edited = _spec(items=[_item("Item # 99", wbs="2.0", cost_code="05-100",
                                crew_id="crew_lab_2")])
    plan = plan_sync(base, edited)
    assert len(plan.item_ops) == 1
    op = plan.item_ops[0]
    assert op.kind == "create"
    assert op.wbs == "2.0"
    assert op.cost_code == "05-100"
    assert op.crew_id == "crew_lab_2"


def test_plan_sync_edited_id_not_in_base_raises_key_error():
    """Documented design behavior: if an edited item claims an
    estimate_item_id not present in base_spec, plan_sync raises KeyError.
    The caller is expected to re-fetch base_spec on drift."""
    base = _spec(items=[_synced(100, "Item # 1")])
    edited = _spec(items=[_synced(999, "Item # 1")])          # id 999 not in base
    with pytest.raises(KeyError):
        plan_sync(base, edited)


# ---- Unanchored-item reconciliation by item_no (issue #250) ---------------

def test_plan_sync_unanchored_item_matching_unanchored_base_is_not_a_create():
    """The #250 near-miss: a hand-authored spec whose BM rows were created by
    another path carries NO estimate_item_id anchors on EITHER side. The old
    code classified every edited item as new purely on the absent id and would
    have emitted `create` for items that already exist in the target estimate —
    duplicating live bid items. When an edited item with no id matches a base
    item by item_no, and the base row also has no anchor, we can neither create
    (duplicate) nor update (no anchor): emit no op and warn."""
    base = _spec(items=[_item("Item # 1", description="Mob", qty=1, uom="LS")])
    edited = _spec(items=[_item("Item # 1", description="Mob", qty=1, uom="LS")])
    plan = plan_sync(base, edited)
    assert plan.item_ops == []                                # NOT a create
    assert len(plan.warnings) == 1
    assert "Item # 1" in plan.warnings[0]
    assert "anchor" in plan.warnings[0].lower()


def test_plan_sync_reproduces_250_two_unanchored_items_zero_creates():
    """Verbatim reporter scenario: two items, both already in BM, both authored
    without anchors. The rendered plan proposed CREATING both. Correct output is
    zero item ops (nothing safely syncable) plus one warning per blocked item —
    not two creates that would duplicate a live bid closing that afternoon."""
    base = _spec(items=[
        _item("Item # 1", description="Mobilization", qty=1, uom="LS"),
        _item("Item # 2", description="Headwall",
              qty="={ref:takeoff.total_cy}", uom="CY"),
    ])
    edited = _spec(items=[
        _item("Item # 1", description="Mobilization", qty=1, uom="LS"),
        _item("Item # 2", description="Headwall",
              qty="={ref:takeoff.total_cy}", uom="CY"),
    ])
    plan = plan_sync(base, edited)
    assert [op.kind for op in plan.item_ops] == []
    assert len(plan.warnings) == 2


def test_plan_sync_unanchored_edited_recovers_anchor_from_base_by_item_no():
    """If the edited spec dropped its anchor but the base snapshot still carries
    a valid estimate_item_id for the same item_no, reconcile by item_no and
    recover the anchor — emit an id-anchored update, never a create."""
    base = _spec(items=[_synced(100, "Item # 1", qty=1)])
    edited = _spec(items=[_item("Item # 1", qty=240, uom="LS")])   # no id
    plan = plan_sync(base, edited)
    assert len(plan.item_ops) == 1
    op = plan.item_ops[0]
    assert op.kind == "update"
    assert op.estimate_item_id == 100
    assert op.changed_fields == ["qty"]
    assert plan.warnings == []


def test_plan_sync_recovered_anchor_item_is_not_also_deleted():
    """Recovering an anchor by item_no must mark that base id as seen, so the
    delete pass doesn't then emit a phantom delete for the very row we matched."""
    base = _spec(items=[_synced(100, "Item # 1", qty=1)])
    edited = _spec(items=[_item("Item # 1", qty=240, uom="LS")])   # no id
    plan = plan_sync(base, edited)
    assert [op.kind for op in plan.item_ops] == ["update"]         # no delete


def test_plan_sync_genuinely_new_unanchored_item_still_creates():
    """An unanchored edited item with NO matching item_no in base is genuinely
    new and must still create — the fix must not suppress legitimate creates."""
    base = _spec(items=[_synced(100, "Item # 1", qty=1)])
    edited = _spec(items=[
        _synced(100, "Item # 1", qty=1),
        _item("Item # 99", description="Punchlist", qty=1, uom="LS"),
    ])
    plan = plan_sync(base, edited)
    creates = [op for op in plan.item_ops if op.kind == "create"]
    assert len(creates) == 1
    assert creates[0].item_no == "Item # 99"
    assert plan.warnings == []


# ---- Render ----------------------------------------------------------------

from estimating_tools.estimate_spec.sync import render_sync_plan


def test_render_sync_plan_empty_plan_shows_heading_summary_and_three_sections():
    plan = SyncPlan()
    out = render_sync_plan(plan)
    assert out.startswith("# Sync plan\n\n")
    assert "0 rate_ops · 0 crew_ops · 0 item_ops." in out
    assert "## Rates (create only)" in out
    assert "## Crews" in out
    assert "## Items" in out
    assert "Confirm to write to BidSheet.ai." in out
    assert not out.endswith("\n")                             # md_table contract


def test_render_sync_plan_renders_warnings_prominently():
    """When plan_sync blocks unsafe creates (issue #250), render_sync_plan must
    surface those warnings loudly — a plan that silently drops items reads as
    'nothing to sync' and hides the near-miss."""
    plan = SyncPlan(warnings=[
        "Item 'Item # 1' exists in the base estimate but carries no anchor; "
        "skipped to avoid a duplicate.",
    ])
    out = render_sync_plan(plan)
    assert "## Warnings" in out
    assert "Item # 1" in out
    # Warnings appear ahead of the item table so a reviewer sees them first.
    assert out.index("## Warnings") < out.index("## Items")


def test_render_sync_plan_no_warnings_section_when_none():
    """No warnings → no Warnings heading (don't clutter the common case)."""
    out = render_sync_plan(SyncPlan())
    assert "## Warnings" not in out


def test_render_sync_plan_summary_reflects_op_counts():
    plan = SyncPlan(
        rate_ops=[RateOp(kind="create", trade="LAB", rate=95)],
        crew_ops=[CrewOp(kind="create", crew_id="crew_x",
                         description="", members=[])],
        item_ops=[
            ItemOp(kind="create", estimate_item_id=None,
                   item_no="Item # 99", description="X",
                   qty=1, uom="LS"),
            ItemOp(kind="delete", estimate_item_id=100,
                   item_no="Item # 1", description="Y",
                   qty=1, uom="LS"),
        ],
    )
    out = render_sync_plan(plan)
    assert "1 rate_op · 1 crew_op · 2 item_ops." in out


def test_render_sync_plan_rate_row_has_trade_and_rate_columns():
    plan = SyncPlan(rate_ops=[RateOp(kind="create", trade="MASON", rate=105.0)])
    out = render_sync_plan(plan)
    assert "| trade | rate |" in out
    assert "| MASON | 105.00 |" in out                        # via format_money


def test_render_sync_plan_crew_row_serializes_members_inline():
    plan = SyncPlan(crew_ops=[
        CrewOp(kind="create", crew_id="crew_ne_5",
               description="Northeast 5-person",
               members=[{"trade": "FORE", "count": 1},
                        {"trade": "OPER", "count": 1},
                        {"trade": "LAB", "count": 3}]),
    ])
    out = render_sync_plan(plan)
    assert "FORE×1, OPER×1, LAB×3" in out


def test_render_sync_plan_item_row_columns_include_kind_id_and_changed():
    plan = SyncPlan(item_ops=[
        ItemOp(kind="update", estimate_item_id=100,
               item_no="Item # 1A", description="Concrete Outfall",
               qty=240, uom="CY", changed_fields=["item_no", "qty"]),
    ])
    out = render_sync_plan(plan)
    assert ("| kind | estimate_item_id | item_no | description | qty | uom "
            "| wbs | cost_code | crew_id | changed |") in out
    assert ("| update | 100 | Item # 1A | Concrete Outfall | 240 | CY "
            "| - | - | - | item_no; qty |") in out


def test_render_sync_plan_item_create_shows_dash_for_estimate_item_id():
    plan = SyncPlan(item_ops=[
        ItemOp(kind="create", estimate_item_id=None,
               item_no="Item # 99", description="New",
               qty=1, uom="LS"),
    ])
    out = render_sync_plan(plan)
    assert "| create | - | Item # 99 |" in out


def test_render_sync_plan_qty_formula_passes_through_unchanged():
    """A formula qty in an ItemOp renders verbatim in the review artifact
    (we can't resolve formulas without a workbook context)."""
    plan = SyncPlan(item_ops=[
        ItemOp(kind="update", estimate_item_id=100,
               item_no="Item # 1", description="Task",
               qty="={ref:takeoff.ftg_cy}", uom="CY",
               changed_fields=["qty"]),
    ])
    out = render_sync_plan(plan)
    assert "={ref:takeoff.ftg_cy}" in out


def test_render_sync_plan_qty_float_trims_trailing_zeros():
    """format_qty trims trailing zeros: 1.5 → '1.5', 240.0 → '240'."""
    plan = SyncPlan(item_ops=[
        ItemOp(kind="update", estimate_item_id=100,
               item_no="Item # 1", description="Task",
               qty=1.5, uom="CY", changed_fields=["qty"]),
        ItemOp(kind="update", estimate_item_id=200,
               item_no="Item # 2", description="Task",
               qty=240.0, uom="CY", changed_fields=["qty"]),
    ])
    out = render_sync_plan(plan)
    assert "| 1.5 |" in out
    assert "| 240 |" in out


def test_render_sync_plan_escapes_newlines_in_description_cells():
    """A description containing a literal newline must not break the table
    grammar: sync.py escapes description cells via escape_string_field (same
    convention as compact.py), so every rendered line is a valid `|` row and
    the artifacts_html grammar parser accepts the whole artifact."""
    plan = SyncPlan(
        crew_ops=[
            CrewOp(kind="create", crew_id="crew_x",
                   description="line one\nline two", members=[]),
        ],
        item_ops=[
            ItemOp(kind="create", estimate_item_id=None,
                   item_no="Item # 1", description="left\nright",
                   qty=1, uom="LS"),
        ],
    )
    out = render_sync_plan(plan)

    # Every non-blank line inside a table is a complete `| ... |` row:
    for ln in out.split("\n"):
        if ln.startswith("|"):
            assert ln.rstrip().endswith("|"), f"broken table row: {ln!r}"

    # Escaped form present; raw newline never leaks mid-row:
    assert "line one\\nline two" in out
    assert "left\\nright" in out

    # Strongest check: the whole artifact fits the render grammar.
    from estimating_tools.artifacts_html import _parse_blocks
    _parse_blocks(out)                                        # must not raise


# ---- Integration -----------------------------------------------------------

from pathlib import Path

import yaml

from estimating_tools.estimate_spec.compact import parse_compact, render_compact
from estimating_tools.estimate_spec.format_pack import load_pack

ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"
ALT_SAMPLE = ALT_DIR / "examples" / "sample.estimate.yaml"


def _mixed_edit_plan():
    """Load the alt pack's example, synthesize ids, apply mixed edits
    (rename + wbs tweak + add + delete), and run plan_sync."""
    base_spec = yaml.safe_load(ALT_SAMPLE.read_text(encoding="utf-8"))
    # Populate synthetic ids so items enter the "synced" branch:
    for i, item in enumerate(base_spec["items"], start=1):
        item["estimate_item_id"] = i * 100                    # 100, 200, 300

    text = render_compact(base_spec)
    # Edit 1: rename Item 2 → Item 2A (id-anchored):
    edited = text.replace("Item 2", "Item 2A")
    # Edit 2: delete Item 1 by dropping its row:
    lines = [ln for ln in edited.splitlines() if "Item 1" not in ln]
    edited = "\n".join(lines)
    # Edit 3: add a new item:
    new_row = "| - | 5.0 | - | - | Item 9 | Punchlist | - | - | 1 | LS | - |"
    edited = edited + "\n" + new_row

    edited_spec = parse_compact(edited, base_spec=base_spec, pack=load_pack(ALT_DIR))
    return base_spec, plan_sync(base_spec, edited_spec)


def test_plan_sync_integration_on_the_alt_pack_mixed_edits():
    """Load the alt pack's example, synthesize ids, apply mixed edits
    (rename + wbs tweak + add + delete), run plan_sync, assert the expected
    ops appear."""
    base_spec, plan = _mixed_edit_plan()

    # No new rates or crews were added in the edits:
    assert plan.rate_ops == []
    assert plan.crew_ops == []

    # Three item_ops: rename Item 2 (update), delete Item 1, create Item 9.
    kinds = sorted(op.kind for op in plan.item_ops)
    assert kinds == ["create", "delete", "update"]

    ops_by_kind = {op.kind: op for op in plan.item_ops}

    # Update (rename):
    upd = ops_by_kind["update"]
    assert upd.estimate_item_id == 200                        # Item 2's synthetic id
    assert upd.item_no == "Item 2A"
    assert upd.changed_fields == ["item_no"]

    # Delete (Item 1):
    dele = ops_by_kind["delete"]
    assert dele.estimate_item_id == 100
    assert dele.item_no == "Item 1"

    # Create (Item 9):
    cre = ops_by_kind["create"]
    assert cre.estimate_item_id is None
    assert cre.item_no == "Item 9"
    assert cre.description == "Punchlist"


def test_render_sync_plan_on_integration_plan_produces_valid_markdown():
    """Confirm the integration plan renders without errors and includes all
    three item ops in the Items section."""
    _base_spec, plan = _mixed_edit_plan()

    out = render_sync_plan(plan)
    assert "# Sync plan" in out
    assert "3 item_ops." in out
    assert "Item 2A" in out
    assert "Item 9" in out
    assert "Confirm to write to BidSheet.ai." in out


def test_render_sync_plan_item_row_shows_metadata_columns():
    plan = SyncPlan(item_ops=[
        ItemOp(kind="update", estimate_item_id=100,
               item_no="Item # 1", description="Mob", qty=1, uom="LS",
               wbs="1.2", cost_code="02-110", crew_id="crew_lab_2",
               changed_fields=["wbs", "cost_code", "crew_id"]),
    ])
    out = render_sync_plan(plan)
    assert ("| kind | estimate_item_id | item_no | description | qty | uom "
            "| wbs | cost_code | crew_id | changed |") in out
    assert ("| update | 100 | Item # 1 | Mob | 1 | LS "
            "| 1.2 | 02-110 | crew_lab_2 | wbs; cost_code; crew_id |") in out


def test_rate_op_defaults_to_a_flat_labor_rate():
    op = RateOp(kind="create", trade="LAB", rate=95.0)
    assert op.resource_kind == "labor"
    assert (op.base, op.burden_pct, op.fringe, op.includes_operator) == (None, None, None, False)


def test_plan_sync_carries_a_labor_breakdown():
    base = _spec(rate_table=[{"trade": "FORE", "rate": 150}])
    edited = _spec(rate_table=[
        {"trade": "FORE", "rate": 150},
        {"trade": "Pipelayer", "rate": 81.89, "base": 48.10, "burden_pct": 0.32, "fringe": 18.40}])
    (op,) = plan_sync(base, edited).rate_ops
    assert op == RateOp(kind="create", trade="Pipelayer", rate=81.89,
                        base=48.10, burden_pct=0.32, fringe=18.40)


def test_plan_sync_carries_an_equipment_rate():
    base = _spec(rate_table=[{"trade": "FORE", "rate": 150}])
    edited = _spec(rate_table=[
        {"trade": "FORE", "rate": 150},
        {"trade": "Excavator, 320 class", "rate": 145.0, "kind": "equipment",
         "includes_operator": True}])
    (op,) = plan_sync(base, edited).rate_ops
    assert op.resource_kind == "equipment" and op.includes_operator is True
