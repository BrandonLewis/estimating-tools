"""Two structurally different packs through one engine (Decision 3)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.scaffold import scaffold_spec, validate_spec

DEMO_DIR = fp.ENGINE_DIR / "packs" / "demo"
EXAMPLE = DEMO_DIR / "examples" / "demo-pipeline.estimate.yaml"
GOLDEN = fp.ENGINE_DIR / "tests" / "fixtures" / "demo-pipeline.golden.json"

ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"
ALT_EXAMPLE = ALT_DIR / "examples" / "sample.estimate.yaml"


@pytest.fixture(scope="module")
def demo():
    return fp.load_pack(DEMO_DIR)


@pytest.fixture(scope="module")
def alt():
    return fp.load_pack(ALT_DIR)


def _example():
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def _alt_example():
    return yaml.safe_load(ALT_EXAMPLE.read_text(encoding="utf-8"))


def test_alt_pack_loads_and_renders(tmp_path):
    pack = fp.load_pack(ALT_DIR)
    spec = yaml.safe_load(ALT_EXAMPLE.read_text(encoding="utf-8"))
    validate_spec(spec, pack=pack)
    B.generate(spec, pack).save(tmp_path / "alt.xlsx")
    assert (tmp_path / "alt.xlsx").exists()


def test_the_packs_share_no_vocabulary(demo, alt):
    for key in ("trades", "cost_blocks"):
        assert not set(demo.vocabulary[key]) & set(alt.vocabulary[key]), key
    assert not set(demo.units) & set(alt.units)
    assert not (set(demo.recipes["recipes"]) - {"cover"}) & (set(alt.recipes["recipes"]) - {"cover"})
    assert not set(demo.recipes["globals"]) & set(alt.recipes["globals"])
    assert demo.recipes["recipes"]["cover"]["sheet_name"] != alt.recipes["recipes"]["cover"]["sheet_name"]


def test_the_demo_example_validates_against_the_demo_pack_only(demo, alt):
    validate_spec(_example(), pack=demo)
    with pytest.raises(ValueError):
        validate_spec(_example(), pack=alt)


def test_the_alt_example_validates_against_the_alt_pack_only(demo, alt):
    validate_spec(_alt_example(), pack=alt)
    with pytest.raises(ValueError):
        validate_spec(_alt_example(), pack=demo)


def test_the_demo_example_renders(demo):
    wb = B.generate(_example(), demo)
    assert wb.sheetnames[0] == "Bid Summary"
    assert "Rates" in wb.sheetnames
    lookups = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row
               if isinstance(c.value, str) and "VLOOKUP" in c.value]
    assert lookups and all("'Rates'!$A$" in f for f in lookups)
    for ws in wb.worksheets:                     # the A:F grid: nothing written past F
        assert ws.max_column <= 6, ws.title


def test_example_cost_codes_come_from_the_seed(demo):
    scheme = {c["code"] for c in demo.seed["cost_codes"]}
    assert {i["cost_code"] for i in _example()["items"]} <= scheme


def test_seed_crews_use_only_permitted_trades(demo):
    trades = set(demo.vocabulary["trades"])
    for crew in demo.seed["crews"]:
        assert {m["trade"] for m in crew["members"]} <= trades


def _values(wb):
    return {ws.title: {c.coordinate: c.value for row in ws.iter_rows() for c in row
                       if c.value is not None}
            for ws in wb.worksheets}


def test_the_demo_golden(demo):
    got = json.loads(json.dumps(_values(B.generate(_example(), demo)), default=str))
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    assert got == json.loads(GOLDEN.read_text())


# ---- A2: extra tools refuse a pack that does not declare support ----------
#
# The demo pack stays the pack that declares no capabilities, so refusal is
# still exercised: `summarize`/`artifact` refuse a pack that never opted in.
# The alt pack is the fixture that DOES opt in (its format.yaml declares
# `supports: [summarize, artifact]`) — it's the only pack left, once the
# reference pack departs, that can prove those two capability-gated modules
# still work.

def test_only_alt_declares_the_extra_tools(demo, alt):
    assert demo.supports == frozenset()
    assert alt.supports == frozenset({"summarize", "artifact"})


def test_alt_pack_declares_its_own_crew_factor_default(alt):
    """A pack declaring `supports: summarize` must state labor.crew_factor_default
    (format_pack.py enforces this at load) — alt's is 2, its own choice,
    distinct from the reference pack's 1."""
    assert alt.labor["crew_factor_default"] == 2


def test_summarize_refuses_a_pack_that_does_not_support_it(demo):
    from estimating_tools.estimate_spec.summarize import summarize
    with pytest.raises(fp.FormatPackError, match="pack 'demo' does not support summarize"):
        summarize(_example(), pack=demo)


def test_summarize_prices_the_alt_pack(alt):
    """The pack that DOES declare support: summarize actually prices —
    the property demo's refusal alone can't prove."""
    from estimating_tools.estimate_spec.summarize import summarize
    result = summarize(_alt_example(), pack=alt)
    assert result["bid_total"] > 0
    assert len(result["items"]) == 3


def test_cli_summarize_refuses_a_pack_that_does_not_support_it(capsys):
    from estimating_tools.estimate_spec.cli import main
    assert main(["summarize", str(EXAMPLE), "--format", str(DEMO_DIR)]) == 2
    captured = capsys.readouterr()
    assert "format pack error" in captured.err
    assert "does not support summarize" in captured.err
    assert "materials" not in captured.out.lower()


def test_cli_summarize_prices_the_alt_pack(capsys):
    from estimating_tools.estimate_spec.cli import main
    assert main(["summarize", str(ALT_EXAMPLE), "--format", str(ALT_DIR)]) == 0
    assert "BID" in capsys.readouterr().out


def test_the_artifact_parser_refuses_a_pack_that_does_not_support_it(demo):
    from estimating_tools.estimate_spec.artifact import parse_item
    with pytest.raises(fp.FormatPackError, match="pack 'demo' does not support artifact"):
        parse_item("## Metadata\n", item_no="1", pack=demo)


def test_the_artifact_round_trips_on_the_alt_pack(alt):
    """The pack that DOES declare support: artifact actually renders/parses."""
    from estimating_tools.estimate_spec.artifact import render_item, parse_item
    item = _alt_example()["items"][1]                   # the geometry work_item
    text = render_item(item, pack=alt)
    assert text.startswith(f"# {item['item_no']}\n\n")
    assert parse_item(text, item_no=item["item_no"], pack=alt) == item


# ---- A3: a unit placed with `sheet:` publishes into its target's namespace --

def test_a_targeted_units_exports_belong_to_its_target_sheet(demo):
    builder = B.EstimateBuilder(_example(), demo)
    wb = builder.run()
    assert "rates.table" in builder.exports["Rates"]
    hosts = [s for s, exp in builder.exports.items() if s != "Rates" and "rates.table" in exp]
    assert hosts == []
    lookups = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row
               if isinstance(c.value, str) and "VLOOKUP" in c.value]
    assert lookups and all("'Rates'!$A$" in f for f in lookups)


# ---- A5: every shipped seed is self-consistent ------------------------------

@pytest.mark.parametrize("which", ["demo", "alt"])
def test_a_config_built_from_the_seed_passes_cross_reference_checks(which, request):
    from estimating_tools.estimate_spec.validate import validate_cross_references
    seed = request.getfixturevalue(which).seed
    config = {"rate_table": [{"trade": t, "rate": 0} for t in seed["rate_table_trades"]],
              "crews": seed.get("crews") or [],
              "items": []}
    validate_cross_references(config)


# ---- Task 4: scaffold is pack-driven, not accidentally compatible ---------

def _mini_manifest():
    """A single mobilization-class bid item — enough to exercise each pack's
    seed.scaffold roles (rate-host recipe/sheet/prefix) without tripping
    either pack's own takeoff requirement on its default item recipe."""
    from estimating_tools.intake.bid_frame import normalize_bid_items
    from estimating_tools.intake.manifest import ProjectManifest

    raw = [{"item_number": "1", "description": "Mobilization", "unit": "LS",
            "estimated_quantity": 1, "schedule": "Base Bid"}]
    m = ProjectManifest(name="Two-Pack Scaffold Check", organization_id=0)
    m.set_bid_frame(normalize_bid_items(raw), snapshot_at="2026-01-01T00:00:00+00:00")
    return m


def test_scaffold_is_pack_driven_not_accidentally_compatible(demo, alt):
    """Scaffold each pack's own spec, validate it against its own pack (must
    pass) and against the other pack (must fail) — the property that proves
    scaffold.py reads recipe/sheet/slot roles from the pack rather than
    hardcoding one org's names."""
    demo_spec = scaffold_spec(_mini_manifest(), pack=demo).spec
    alt_spec = scaffold_spec(_mini_manifest(), pack=alt).spec

    validate_spec(demo_spec, pack=demo)
    validate_spec(alt_spec, pack=alt)

    with pytest.raises(ValueError):
        validate_spec(demo_spec, pack=alt)
    with pytest.raises(ValueError):
        validate_spec(alt_spec, pack=demo)
