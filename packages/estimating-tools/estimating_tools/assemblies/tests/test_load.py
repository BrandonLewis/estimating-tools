"""Estimate-context assembly loading (issue #201): bind assemblies to a bid/
estimate item and emit BidSheet.ai payloads with the roll-up contract — and its
two silent traps — enforced in ONE place so the wrong encoding is unauthorable.
"""
import pytest

from estimating_tools.assemblies.excel import build_assembly_load
from estimating_tools.assemblies.load_cli import main as asm_load_main
from estimating_tools.assemblies.load_model import (
    AssemblyLoadItem, CanonicalAssemblyLoad, LoadAssembly, LoadComponent,
)
from estimating_tools.assemblies.plan import (
    AssemblyLoadPlan, plan_assembly_load, render_assembly_load_plan,
)


def _crew_assembly(**kw) -> LoadAssembly:
    """A legible CREW assembly: production_rate carries the crew-hours, each
    component is one trade (quantity=headcount, unit_cost=hourly rate)."""
    defaults = dict(
        name="Set-Faces crew", assembly_type="CREW", cost_code="03-300",
        production_rate=43.65, production_unit="HOURS",
        components=[
            LoadComponent("labor", "01 Foreman", quantity=1.0, unit="HR",
                          unit_cost=175.0, trade="foreman"),
            LoadComponent("labor", "02 Carpenter", quantity=2.0, unit="HR",
                          unit_cost=165.0, trade="carpenter"),
            LoadComponent("material", "03 Ready-mix", quantity=12.0, unit="CY",
                          unit_cost=145.0),
        ],
    )
    defaults.update(kw)
    return LoadAssembly(**defaults)


def _load(assemblies=None, estimate_item_id=5001, bid_item_code="51-0510") \
        -> CanonicalAssemblyLoad:
    return CanonicalAssemblyLoad(items=[AssemblyLoadItem(
        estimate_item_id=estimate_item_id, bid_item_code=bid_item_code,
        assemblies=assemblies if assemblies is not None else [_crew_assembly()],
    )])


def test_plan_binds_assemblies_to_the_estimate_item():
    plan = plan_assembly_load(_load(), estimate_id=900)
    assert isinstance(plan, AssemblyLoadPlan) and plan.estimate_id == 900
    a = plan.assemblies[0]
    assert a["name"] == "Set-Faces crew"
    # estimate context, bound to the bid/estimate item — NOT template/org context
    assert a["context"] == "estimate"
    assert a["context_id"] == 5001 and a["estimate_item_id"] == 5001
    assert a["estimate_id"] == 900
    assert a["bid_item_code"] == "51-0510"
    assert a["cost_code"] == "03-300"


def test_production_rate_and_labor_basis_ride_the_payload():
    a = plan_assembly_load(_load(), estimate_id=1).assemblies[0]
    assert a["production_rate"] == 43.65 and a["production_unit"] == "HOURS"
    labor = [c for c in a["components"] if c["component_type"] == "labor"]
    assert labor and all(c["labor_cost_basis"] == "production" for c in labor)


def test_production_basis_labor_without_production_rate_is_unauthorable():
    """The #201 trap: a CREW assembly with production-basis labor but no
    production_rate rolls up $0 labor (or forces the inverse encoding — hours
    pre-multiplied into quantity). The planner must refuse it, not emit it."""
    bad = _crew_assembly(production_rate=None)
    with pytest.raises(ValueError, match="production_rate"):
        plan_assembly_load(_load([bad]), estimate_id=1)

    bad_zero = _crew_assembly(production_rate=0.0)
    with pytest.raises(ValueError, match="production_rate"):
        plan_assembly_load(_load([bad_zero]), estimate_id=1)


def test_zero_quantity_component_is_unauthorable():
    """BidSheet.ai coerces quantity=0 -> 1.0, inventing a phantom charge. A $0
    placeholder must be omitted, not stored — so the planner refuses quantity=0
    rather than pass the trap through."""
    bad = _crew_assembly(components=[
        LoadComponent("material", "Placeholder", quantity=0.0, unit="EA",
                      unit_cost=300.0),
    ])
    with pytest.raises(ValueError, match="quantity"):
        plan_assembly_load(_load([bad]), estimate_id=1)


def test_flat_basis_labor_needs_no_production_rate():
    """Only production-basis labor depends on production_rate. A flat-basis
    labor buildup (all-in cost already in quantity×unit_cost) is fine without
    it."""
    ok = LoadAssembly(
        name="T&M patch", assembly_type="", production_rate=None,
        components=[
            LoadComponent("labor", "Laborer", quantity=8.0, unit="HR",
                          unit_cost=150.0, labor_cost_basis="flat"),
        ],
    )
    a = plan_assembly_load(_load([ok]), estimate_id=1).assemblies[0]
    assert a["production_rate"] is None
    assert a["components"][0]["labor_cost_basis"] == "flat"


def test_unknown_labor_cost_basis_is_rejected():
    """A typo like "prodution" would slip past the `== "production"` guard and
    emit a $0-labor assembly. An unknown basis on a labor component must be a
    hard authoring error, not a silent bypass."""
    bad = _crew_assembly(components=[
        LoadComponent("labor", "Foreman", quantity=1.0, unit="HR",
                      unit_cost=175.0, labor_cost_basis="prodution"),
    ])
    with pytest.raises(ValueError, match="labor_cost_basis"):
        plan_assembly_load(_load([bad]), estimate_id=1)


def test_rate_resolution_routes_and_flags_like_the_push_planner():
    asm = LoadAssembly(
        name="A", production_rate=10.0,
        components=[
            LoadComponent("labor", "Crew", rate_ref="CARP"),
            LoadComponent("subcontractor", "Sub", rate_ref="SUB-1"),
        ],
    )
    a = plan_assembly_load(_load([asm]), estimate_id=1).assemblies[0]
    assert a["components"][0]["rate_resolution"] == {"kind": "labor", "key": "CARP"}
    assert a["components"][1]["rate_resolution"] is None
    assert "SUB-1" in a["rate_refs"] and "CARP" not in a["rate_refs"]


def test_invalid_component_type_raises():
    asm = LoadAssembly(name="Bad", production_rate=1.0,
                       components=[LoadComponent("widget", "x", quantity=1.0)])
    with pytest.raises(ValueError, match="component_type"):
        plan_assembly_load(_load([asm]), estimate_id=1)


def test_rate_ref_without_unit_cost_is_zeroed_not_dropped():
    asm = LoadAssembly(
        name="A", production_rate=1.0,
        components=[LoadComponent("subcontractor", "Sub", quantity=1.0,
                                  rate_ref="SUB-1")],
    )
    a = plan_assembly_load(_load([asm]), estimate_id=1).assemblies[0]
    assert a["components"][0]["unit_cost"] == 0.0


# ---------- render_assembly_load_plan (issue #201, piece 1) ----------

def test_render_shows_rolled_up_costs_not_bare_inputs():
    """The whole point of the load render: production-basis labor is shown
    extended by production_rate (qty × unit_cost × crew-hours), material stays a
    plain qty × unit_cost. Foreman 1×175×43.65, Carpenter 2×165×43.65, Ready-mix
    12×145 → assembly 23,783.25."""
    text = render_assembly_load_plan(plan_assembly_load(_load(), estimate_id=1))
    assert "7638.75" in text      # 1 × 175 × 43.65
    assert "14404.50" in text     # 2 × 165 × 43.65
    assert "1740.00" in text      # 12 × 145 (material — NOT × production_rate)
    assert "23783.25" in text     # assembly + grand total


def test_render_summary_counts_items_assemblies_components_and_total():
    text = render_assembly_load_plan(plan_assembly_load(_load(), estimate_id=1))
    first_line = text.splitlines()[2]  # after "# Assembly load plan" + blank
    assert "1 estimate item" in first_line
    assert "1 assembly" in first_line
    assert "3 components" in first_line
    assert "total 23783.25" in first_line


def test_render_basis_column_is_dash_for_non_labor():
    """A material row must not show 'production' in the basis column even though
    the payload carries labor_cost_basis on every component — that would read as
    a $0-crew trap that doesn't apply."""
    text = render_assembly_load_plan(plan_assembly_load(_load(), estimate_id=1))
    ready_mix_row = next(l for l in text.splitlines() if "Ready-mix" in l)
    cells = [c.strip() for c in ready_mix_row.split("|")]
    assert "production" not in cells       # basis cell is "-", not "production"


def test_render_flags_nonroutable_rate_refs():
    asm = LoadAssembly(
        name="Sub work", production_rate=None,
        components=[LoadComponent("subcontractor", "Paving sub", quantity=1.0,
                                  unit_cost=50000.0, rate_ref="PAVE-1")],
    )
    text = render_assembly_load_plan(plan_assembly_load(_load([asm]), estimate_id=1))
    assert "## Flagged" in text
    assert "PAVE-1" in text
    assert "non-routable rate ref" in text.splitlines()[2]


def test_render_groups_multiple_items_by_label():
    load = CanonicalAssemblyLoad(items=[
        AssemblyLoadItem(estimate_item_id=101, bid_item_code="51-0510",
                         assemblies=[_crew_assembly()]),
        AssemblyLoadItem(estimate_item_id=202, bid_item_code="19-2003",
                         assemblies=[_crew_assembly(name="Backfill crew")]),
    ])
    text = render_assembly_load_plan(plan_assembly_load(load, estimate_id=9))
    assert "2 estimate items" in text.splitlines()[2]
    assert "101 (51-0510)" in text and "202 (19-2003)" in text


# ---------- build_assembly_load (issue #201, piece 2) ----------

def _row(**kw) -> dict:
    base = dict(
        estimate_item_id=101, bid_item_code="51-0510", assembly="Set-Faces crew",
        assembly_type="CREW", cost_code="03-300", production_rate=43.65,
        production_unit="HOURS", component_type="labor", component="01 Foreman",
        quantity=1.0, unit="HR", unit_cost=175.0, labor_cost_basis="production",
    )
    base.update(kw)
    return base


def test_build_load_groups_rows_by_item_then_assembly():
    rows = [
        _row(component="01 Foreman", quantity=1.0, unit_cost=175.0),
        _row(component="02 Carpenter", component_type="labor", quantity=2.0,
             unit_cost=165.0),
        _row(estimate_item_id=202, bid_item_code="19-2003", assembly="Backfill crew",
             component="01 Operator", quantity=1.0, unit_cost=150.0),
    ]
    load = build_assembly_load(rows)
    assert [i.estimate_item_id for i in load.items] == [101, 202]
    first = load.items[0]
    assert first.bid_item_code == "51-0510"
    assert len(first.assemblies) == 1 and len(first.assemblies[0].components) == 2
    assert first.assemblies[0].production_rate == 43.65
    assert load.items[1].assemblies[0].name == "Backfill crew"


def test_build_load_defaults_labor_basis_to_production():
    load = build_assembly_load([_row(labor_cost_basis="")])
    assert load.items[0].assemblies[0].components[0].labor_cost_basis == "production"


def test_build_load_blank_estimate_item_id_raises():
    with pytest.raises(ValueError, match="estimate_item_id"):
        build_assembly_load([_row(estimate_item_id="")])


def test_build_load_missing_binding_column_raises():
    rows = [{"assembly": "A", "component_type": "labor", "component": "Foreman"}]
    with pytest.raises(ValueError, match="estimate_item_id"):
        build_assembly_load(rows)


def test_build_load_feeds_the_planner_end_to_end():
    """The builder's output must plan cleanly — the traps fire on the built
    model exactly as on a hand-built one."""
    load = build_assembly_load([_row()])
    plan = plan_assembly_load(load, estimate_id=7)
    assert plan.assemblies[0]["context"] == "estimate"
    assert plan.assemblies[0]["context_id"] == 101


# ---------- asm-load CLI (issue #201, piece 2) ----------

def test_asm_load_cli_reads_json_rows(tmp_path, capsys):
    import json
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps([_row()]), encoding="utf-8")
    out_path = tmp_path / "load.canonical.json"
    rc = asm_load_main([str(rows_path), "-o", str(out_path)])
    assert rc == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert doc["items"][0]["estimate_item_id"] == 101
    assert doc["items"][0]["assemblies"][0]["production_rate"] == 43.65


def test_asm_load_cli_rejects_non_list_json(tmp_path, capsys):
    import json
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"items": []}), encoding="utf-8")
    rc = asm_load_main([str(bad)])
    assert rc == 1
    assert "list of row objects" in capsys.readouterr().err


# ---------- input-validation hardening (Copilot review on #237) ----------

def test_build_load_fractional_estimate_item_id_raises():
    """The binding key must not silently truncate: 101.9 -> 101 would route the
    load to a different estimate item."""
    with pytest.raises(ValueError, match="estimate_item_id"):
        build_assembly_load([_row(estimate_item_id=101.9)])


def test_build_load_integral_float_estimate_item_id_ok():
    """A spreadsheet cell stored as 101.0 is a legitimate integer id."""
    load = build_assembly_load([_row(estimate_item_id=101.0)])
    assert load.items[0].estimate_item_id == 101


def test_build_load_nonnumeric_quantity_raises():
    """A typo'd quantity must fail loudly, not silently become the 1.0 default
    (that would invent a phantom charge — the exact #201 trap)."""
    with pytest.raises(ValueError, match="quantity"):
        build_assembly_load([_row(quantity="12o")])


def test_build_load_nonnumeric_unit_cost_raises():
    with pytest.raises(ValueError, match="unit_cost"):
        build_assembly_load([_row(unit_cost="~185")])


def test_build_load_blank_quantity_still_defaults():
    """Blank is still 'unset' -> the 1.0 default; only nonblank garbage raises."""
    load = build_assembly_load([_row(quantity="")])
    assert load.items[0].assemblies[0].components[0].quantity == 1.0


def test_build_load_non_dict_row_raises_cleanly():
    """A malformed JSON payload like [1] must raise a handled ValueError, not an
    uncaught AttributeError from r.keys()."""
    with pytest.raises(ValueError, match="object/dict"):
        build_assembly_load([1])


def test_asm_load_cli_non_dict_rows_error(tmp_path, capsys):
    import json
    bad = tmp_path / "rows.json"
    bad.write_text(json.dumps([1, 2]), encoding="utf-8")
    rc = asm_load_main([str(bad)])
    assert rc == 1
    assert "object/dict" in capsys.readouterr().err


def test_render_counts_distinct_item_ids_not_pairs():
    """Item count keys on estimate_item_id (the binding key); a stray mismatched
    bid_item_code on the same id must not inflate the count."""
    load = CanonicalAssemblyLoad(items=[AssemblyLoadItem(
        estimate_item_id=101, bid_item_code="A",
        assemblies=[_crew_assembly(), _crew_assembly(name="Second crew")],
    )])
    plan = plan_assembly_load(load, estimate_id=1)
    # both assemblies share estimate_item_id 101 -> exactly one item
    assert "1 estimate item;" in render_assembly_load_plan(plan)
