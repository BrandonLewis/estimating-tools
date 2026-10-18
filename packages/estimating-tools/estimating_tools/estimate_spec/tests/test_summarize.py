"""Tests for summarize.py — pure-Python pricing of an estimate spec.

The pinned constants below are hand-derived from the alt pack's own example
(tests/fixtures/packs/alt/examples/sample.estimate.yaml — authored for this
test suite; the arithmetic is shown line by line in comments) so the module
is checked against the spec's own semantics, not against itself. summarize()
requires `supports: summarize` (the alt pack declares it; the legacy_demo
fixture does not — see test_two_packs.py for the refusal side), so every call here passes
`pack=alt` explicitly rather than relying on whichever pack happens to be
bundled by default.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec.format_pack import load_pack
from estimating_tools.estimate_spec.summarize import (
    FormulaError, evaluate, price_item, summarize)

SPEC_DIR = Path(__file__).resolve().parents[1]
ALT_DIR = SPEC_DIR / "tests" / "fixtures" / "packs" / "alt"
SAMPLE = ALT_DIR / "examples" / "sample.estimate.yaml"


@pytest.fixture(scope="module")
def alt():
    return load_pack(ALT_DIR)


@pytest.fixture(scope="module")
def sample_spec():
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result(sample_spec, alt):
    return summarize(sample_spec, pack=alt)


# =============================================================================
# Item 2 ("2 - DUCT RUN", kind: geometry): labor + spreads + cost details.
#
# Geometry lines -> ctx (build_ctx sums every numeric field across lines):
#   ftg_cy = 3.5 + 2.5 = 6.0      wall_cy = 8 + 5   = 13.0
#   ftg_cf = 94.5 + 67.5 = 162.0  wall_cf = 216 + 135 = 351.0
#   total_cy (suffix "cy") = ftg_cy + wall_cy = 19.0   <- item qty
#   total_cf (suffix "cf") = ftg_cf + wall_cf = 513.0
#
# LABOR (crew row = days x rate x count x 8; alt's own crew_factor_default
#   is 2 — see test_two_packs.py::test_alt_pack_declares_its_own_crew_factor_default):
#   slot AA activities Layout 0.3 + Hang 0.2 = 0.5 ; prod_days = 0.5 x 2 = 1.0
#     FITTER "=D{row:prod_days}"    -> days 1.0 -> 1.0x88x1x8 = 704
#     WELDER "=E{row:crew_first}"   -> rides FITTER's 1.0     -> 1.0x91x1x8 = 728
#     RIGGER literal 2 days                                  -> 2x79x1x8   = 1264
#     slot AA subtotal = 704 + 728 + 1264 = 2,696
#   slot BB HELPER literal 3 days                            -> 3x55x1x8   = 1,320
#   labor_total = 2,696 + 1,320 = 4,016
#   foreman_days (FITTER only) = 1.0 (slot AA only; slot BB has no FITTER)
#
# SPREADS (ftg_qty/wall_qty ref the geometry sums; waste stated explicitly):
#   qty_subtotal = ftg_cy x (1+ftg_waste) + wall_cy x (1+wall_waste)
#                = 6.0 x 1.10 + 13.0 x 1.05 = 6.6 + 13.65 = 20.25
#   Rigid hanger kit "=B{row:qty_subtotal}" -> 20.25 x 12  = 243.0
#   Isolation pads   literal 8              -> 8 x 5.5     =  44.0
#   materials_total = 243.0 + 44.0 = 287.0
#
# COST DETAILS (item qty = 19.0; PARTS/LEASE carry the header-price
#   convention — see recipes.yaml's instance_defaults):
#   PARTS  header_price 0.5 x qty 19.0, no lines           = 9.5
#   LEASE  no header_price; Man lift 6 x 210                = 1,260.0
#   cost_detail_total = 9.5 + 1,260.0 = 1,269.5
#
# sub_total = 0 (kind is geometry, not subcontractor)
# ITEM TOTAL = 4,016 + 287.0 + 1,269.5 + 0 = 5,572.5
# =============================================================================

def test_duct_run_item_pinned(result):
    item = result["items"][1]
    assert item["sheet"] == "2 - DUCT RUN"
    assert item["qty"] == pytest.approx(19.0)
    assert item["labor_total"] == pytest.approx(4016.0)
    assert item["foreman_days"] == pytest.approx(1.0)
    assert item["materials_total"] == pytest.approx(287.0)
    assert item["cost_detail_total"] == pytest.approx(1269.5)
    assert item["sub_total"] == pytest.approx(0.0)
    assert item["item_total"] == pytest.approx(5572.5)


# =============================================================================
# Top-level bid. Derivation of the other two items:
#
# "PRE" (preamble, no takeoff/spreads/cost_details): labor slot AA
#   FITTER 1x88x1x8 = 704 ; HELPER 1x55x1x8 = 440 -> labor_total 1,144.
#   item_total = 1,144.
#
# "3 - HANGER SET" (kind: subcontractor): material 24x18 = 432 ; galvanize
#   omitted -> 0 ; tax_rate omitted -> the pack's own default (sub_takeoff's
#   units.yaml default is 0.08, NOT the reference pack's 0.0725 — see
#   test_omitted_tax_rate_matches_the_alt_pack_default) -> tax
#   (432+0)x0.08 = 34.56 ; freight 150 -> sub_total 432+0+34.56+150 = 616.56.
#   labor slot AA FITTER 1x88x1x8=704 + HELPER 1x55x1x8=440 -> 1,144.
#   cost_details VENDOR (no header-price convention) 24x9 = 216.
#   item_total = 1,144 + 0 + 216 + 616.56 = 1,976.56.
#
# subtotal  = 1,144 + 5,572.5 + 1,976.56 = 8,693.06
# markup    = "=E{row:subtotal}*0.10" -> 8,693.06 x 0.10 = 869.306
# bid_total = 8,693.06 + 869.306 = 9,562.366
# =============================================================================

def test_bid_total_pinned(result):
    assert result["items"][0]["item_total"] == pytest.approx(1144.0)
    assert result["items"][2]["item_total"] == pytest.approx(1976.56)
    assert result["subtotal"] == pytest.approx(8693.06)
    assert result["markup"] == pytest.approx(869.306)
    assert result["bid_total"] == pytest.approx(9562.366)


# =============================================================================
# Carry-the-line-above: "=D{r-1}" prices at the previous line's qty
# =============================================================================

def test_cost_detail_carry_the_line_above(alt):
    item = {
        "sheet": "S", "description": "d", "qty": 1, "uom": "LS",
        "cost_details": [{"name": "PARTS", "lines": [
            {"name": "PICKUP", "uom": "Hrs", "qty": 12, "unit_price": 10},
            {"name": "TOOLS", "uom": "Hrs", "qty": "=D{r-1}", "unit_price": 5},
        ]}],
    }
    out = price_item(item, {}, pack=alt)
    # PICKUP 12 x 10 = 120 ; TOOLS rides PICKUP's 12 hrs -> 12 x 5 = 60
    assert out["cost_detail_total"] == pytest.approx(180.0)
    assert out["item_total"] == pytest.approx(180.0)


# =============================================================================
# Subcontractor-kind takeoff bundles material + galvanize + tax + freight
# =============================================================================

def test_subcontractor_takeoff_bundle(alt):
    item = {
        "sheet": "S", "description": "d", "qty": 1, "uom": "EA",
        "takeoff": {
            "kind": "subcontractor",
            "galvanize": 100, "tax_rate": 0.10, "freight": 50,
            "lines": [
                {"item": "bar", "qty": 10, "uom": "FT", "unit_price": 2.5},
                {"item": "pipe", "qty": 4, "uom": "FT", "unit_price": 5},
            ],
        },
    }
    out = price_item(item, {}, pack=alt)
    # material 10x2.5 + 4x5 = 45 ; galv 100 ; tax (45+100)x0.10 = 14.5 ;
    # freight 50 -> 209.5
    assert out["sub_total"] == pytest.approx(209.5)
    assert out["item_total"] == pytest.approx(209.5)


# =============================================================================
# Sandbox: only pure arithmetic survives; everything else refuses loudly.
# `evaluate()` takes no pack — it is pure ctx-in/float-out, unaffected by
# which pack is bundled.
# =============================================================================

def test_sandbox_refuses_dunder_import():
    expr = "=__import__('os').getcwd()"
    with pytest.raises(FormulaError) as exc:
        evaluate(expr, {})
    assert "__import__('os').getcwd()" in str(exc.value)


def test_sandbox_refuses_bare_name():
    with pytest.raises(FormulaError) as exc:
        evaluate("=foreman_days*8", {})
    assert "foreman_days*8" in str(exc.value)


def test_sandbox_refuses_attribute_access():
    with pytest.raises(FormulaError) as exc:
        evaluate("=(1).__class__", {})
    assert "(1).__class__" in str(exc.value)


def test_scientific_notation_is_not_a_cell_ref():
    # Copilot PR-127 catch: "1.5E2" matched the E2 cell-ref pattern and
    # silently carried forward at the default instead of evaluating 150.
    assert evaluate("=1.5E2", {}) == pytest.approx(150.0)
    assert evaluate("=1E3+1", {}) == pytest.approx(1001.0)
    # a REAL column-E ref (operator before the letter) still carries forward
    carries: list = []
    assert evaluate("=2*E3", {}, 5.0, carries=carries, where="w") == 5.0
    assert carries and carries[0]["formula"] == "=2*E3"


def test_wide_column_refs_carry_forward_not_raise():
    # Columns past H are cell refs too — the docstring contract is
    # carry-forward, not FormulaError.
    carries: list = []
    assert evaluate("=$J$13", {}, 0.0, carries=carries) == 0.0
    assert carries


def test_booleans_refuse():
    # YAML turns yes/no into booleans; silently pricing True as 1.0 turns a
    # typo into a quantity. Refuse loudly.
    with pytest.raises(FormulaError):
        evaluate(True, {})
    with pytest.raises(FormulaError):
        evaluate(False, {})


def test_sandbox_refuses_exponentiation():
    # "**" passes a naive * whitelist and "=9**9**9**9" is a CPU pit.
    with pytest.raises(FormulaError):
        evaluate("=2**10", {})


def test_omitted_tax_rate_matches_the_alt_pack_default(alt):
    # alt's sub_takeoff unit declares tax_rate default 0.08 (its OWN choice,
    # not the reference pack's 0.0725) and the generator injects it —
    # summarize must not silently price 0% tax on the same spec.
    item = {"sheet": "s", "takeoff": {
        "kind": "subcontractor",
        "lines": [{"item": "steel", "qty": 100, "uom": "lb",
                   "unit_price": 2.0}]}}
    out = price_item(item, {}, pack=alt)
    assert out["takeoff_tax"] == pytest.approx(200 * 0.08)


def test_carried_forward_is_visible_in_result_and_cli(alt):
    # A load-bearing qty priced at its default must never be silent.
    from estimating_tools.estimate_spec.summarize import render_summary
    spec = {"project": "p", "rate_table": [],
            "items": [{"sheet": "S1", "qty": "=D20",
                       "cost_details": [{"name": "PARTS", "lines": [
                           {"name": "Pickup", "qty": "=E{r+2}",
                            "unit_price": 15}]}]}]}
    result = summarize(spec, pack=alt)
    wheres = [c["where"] for c in result["carried_forward"]]
    assert "S1 qty" in wheres
    assert any("PARTS" in w for w in wheres)
    text = render_summary(result)
    assert "WARNING" in text and "=D20" in text


def test_unknown_ref_raises_naming_the_ref():
    with pytest.raises(FormulaError) as exc:
        evaluate("={ref:missing.target}*2", {})
    assert "missing.target" in str(exc.value)


def test_a_cross_sheet_ref_says_so_instead_of_reading_as_a_typo():
    """A cross-sheet ref is a WORKBOOK address; this module prices from the
    spec alone. Erroring is right, but "unknown ref" sends the author hunting
    for a typo -- the message has to say the value belongs in the pack."""
    with pytest.raises(FormulaError) as exc:
        evaluate("={ref:Crew Rates!rate_sheet.table}*2", {})
    msg = str(exc.value)
    assert "cross-sheet ref" in msg
    assert "Crew Rates!rate_sheet.table" in msg
    assert "pack" in msg
    # a plain typo still reads as a plain typo
    with pytest.raises(FormulaError) as exc:
        evaluate("={ref:missing.target}*2", {})
    assert "cross-sheet" not in str(exc.value)


def test_residual_cell_refs_carry_forward():
    # Cell addresses we cannot resolve without the sheet return the default
    # (graceful carried-forward handling), they are never evaluated.
    assert evaluate("=G120*8", {}) == 0.0
    assert evaluate("=D{row:sum}", {}, default=7.5) == 7.5
    assert evaluate("=E{r-1}", {}) == 0.0


def test_arithmetic_and_refs_evaluate():
    assert evaluate("=810*1.75", {}) == pytest.approx(1417.5)
    assert evaluate("={ref:takeoff.ftg_cy}*2", {"takeoff.ftg_cy": 1.11}) \
        == pytest.approx(2.22)


# =============================================================================
# Markup may be a formula on the cover subtotal ("=E{row:subtotal}*0.10")
# =============================================================================

def test_markup_formula_scales_subtotal(alt):
    spec = {
        "project": "P", "markup": "=E{row:subtotal}*0.10",
        "rate_table": [{"trade": "FITTER", "rate": 100}],
        "items": [{
            "sheet": "S", "description": "d", "qty": 1, "uom": "LS",
            "labor": [{"slot": "AA", "description": "x", "activities": [],
                       "crew": [{"trade": "FITTER", "count": 1, "days": 1}]}],
        }],
    }
    r = summarize(spec, pack=alt)
    # labor 1 x 100 x 1 x 8 = 800 ; markup = 800 x 0.10 = 80
    assert r["subtotal"] == pytest.approx(800.0)
    assert r["markup"] == pytest.approx(80.0)
    assert r["bid_total"] == pytest.approx(880.0)


# =============================================================================
# crew_factor's default is pack policy, not an engine constant (Plan C task 2)
# =============================================================================

def _item_with_unstated_crew_factor():
    return {
        "sheet": "S", "description": "d", "qty": 1, "uom": "LS",
        "labor": [{"slot": "AA", "description": "x",
                   "activities": [{"name": "Form", "factor": 0.5}],
                   "crew": [{"trade": "FITTER", "count": 1, "days": "prod_days"}]}],
    }


def test_crew_factor_default_comes_from_the_pack_not_hardcoded():
    from types import SimpleNamespace
    pack = SimpleNamespace(labor={"crew_factor_default": 9}, vocabulary=None)
    out = price_item(_item_with_unstated_crew_factor(), {"FITTER": 100}, pack=pack)
    # prod_days = 0.5 activity-factor x crew_factor_default 9 = 4.5
    # FITTER 4.5 x 100 x 1 x 8 = 3,600
    assert out["labor_total"] == pytest.approx(3600.0)


def test_crew_factor_default_is_2_on_the_alt_pack(alt):
    """The alt pack states its own crew_factor_default (2) — distinct from
    the reference pack's 1 (which was itself Decision 5's replacement for
    the engine's old hardcoded 5). No test may assume any one of these
    values without naming the pack it came from."""
    out = price_item(_item_with_unstated_crew_factor(), {"FITTER": 100}, pack=alt)
    # prod_days = 0.5 x crew_factor_default 2 = 1.0 ; FITTER 1.0x100x1x8 = 800
    assert out["labor_total"] == pytest.approx(800.0)


def test_an_explicit_crew_factor_still_overrides_the_pack_default(alt):
    item = _item_with_unstated_crew_factor()
    item["labor"][0]["crew_factor"] = 5
    out = price_item(item, {"FITTER": 100}, pack=alt)
    # prod_days = 0.5 x 5 = 2.5 ; FITTER 2.5x100x1x8 = 2,000
    assert out["labor_total"] == pytest.approx(2000.0)


# =============================================================================
# CLI: est-estimate summarize <spec.yaml> --format <pack>
# =============================================================================

def test_cli_summarize_prints_items_and_bid(capsys):
    from estimating_tools.estimate_spec.cli import main
    assert main(["summarize", str(SAMPLE), "--format", str(ALT_DIR)]) == 0
    out = capsys.readouterr().out
    for sheet in ("PRE", "2 - DUCT RUN", "3 - HANGER SET"):
        assert sheet in out
    assert "BID" in out
    assert "9,562" in out          # 8,693.06 + 869.306 markup, rounded


def test_cli_summarize_missing_file(tmp_path, capsys):
    from estimating_tools.estimate_spec.cli import main
    assert main(["summarize", str(tmp_path / "nope.yaml"), "--format", str(ALT_DIR)]) == 1


# =============================================================================
# waste factors come from the pack; spreads summarize cannot read is an error
# =============================================================================

_RATES = {"FITTER": 88.0}


def _spreads_item(spreads: dict) -> dict:
    return {"sheet": "S", "item_no": "1", "description": "d", "qty": 1,
            "spreads": spreads}


def test_omitted_waste_factors_come_from_the_pack_not_a_literal(alt):
    """0.15 / 0.125 were one org's numbers, hardcoded into a module every
    pack declaring `supports: summarize` runs through. The alt pack's units
    declare 0.1 / 0.05, and that is what must be applied."""
    out = price_item(_spreads_item({"ftg_qty": 100, "wall_qty": 100}),
                     _RATES, pack=alt)
    assert out["concrete_qty"] == pytest.approx(100 * 1.10 + 100 * 1.05)


def test_a_waste_factor_on_the_block_still_wins_over_the_pack(alt):
    out = price_item(
        _spreads_item({"ftg_qty": 100, "ftg_waste": 0.5, "wall_qty": 100}),
        _RATES, pack=alt)
    assert out["concrete_qty"] == pytest.approx(100 * 1.5 + 100 * 1.05)


def test_spreads_legs_this_module_cannot_read_raise_instead_of_pricing_zero(alt):
    """A pack whose spreads block names its legs differently used to score
    qty_subtotal = 0 in silence — a wrong bid number, not an error."""
    with pytest.raises(FormulaError) as exc:
        price_item(_spreads_item({"slab_qty": 100, "slab_waste": 0.1}),
                   _RATES, pack=alt)
    assert "alt" in str(exc.value)
    for key in ("ftg_qty", "wall_qty", "ftg_waste", "wall_waste"):
        assert key in str(exc.value)


def test_a_waste_factor_nobody_declares_raises_rather_than_being_invented(alt, tmp_path):
    """With the literals gone, an undeclared waste factor has no value to
    fall back on. summarize must say so rather than quietly apply zero."""
    import shutil

    import yaml as _yaml

    root = tmp_path / "nowaste"
    shutil.copytree(ALT_DIR, root)
    units_path = root / "units.yaml"
    doc = _yaml.safe_load(units_path.read_text(encoding="utf-8"))
    for udef in doc["units"].values():
        for name in ("ftg_waste", "wall_waste"):
            (udef.get("params") or {}).pop(name, None)
    units_path.write_text(_yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    pack = load_pack(root)

    with pytest.raises(FormulaError, match=r"ftg_waste.*will not invent"):
        price_item(_spreads_item({"ftg_qty": 100}), _RATES, pack=pack)


# =============================================================================
# in_summary — a shared-cost sheet is priced, but its dollars reach the bid
# only through the items that carry a share of it.
# =============================================================================
import copy


def _shared(sample_spec):
    spec = copy.deepcopy(sample_spec)
    spec["items"][-1]["in_summary"] = False
    return spec


def test_subtotal_excludes_a_sheet_pushed_into_its_paying_items(sample_spec, alt):
    """Counting it here AND in the shares that reference it is the exact
    double-count the flag exists to prevent."""
    spec = _shared(sample_spec)
    shared_total = summarize(sample_spec, pack=alt)["items"][-1]["item_total"]
    assert shared_total > 0                      # the guard is worth something
    full = summarize(sample_spec, pack=alt)["subtotal"]
    assert summarize(spec, pack=alt)["subtotal"] == pytest.approx(
        full - shared_total)


def test_the_skipped_sheet_is_still_priced_and_still_reported(sample_spec, alt):
    """Out of the SUBTOTAL, not out of the run: an estimator still has to see
    what the shared sheet costs before it is split."""
    spec = _shared(sample_spec)
    items = summarize(spec, pack=alt)["items"]
    assert [i["sheet"] for i in items] == [i["sheet"] for i in
                                           summarize(sample_spec, pack=alt)["items"]]
    assert items[-1]["item_total"] > 0


def test_in_summary_true_is_the_default(sample_spec, alt):
    spec = copy.deepcopy(sample_spec)
    spec["items"][-1]["in_summary"] = True
    assert (summarize(spec, pack=alt)["subtotal"]
            == summarize(sample_spec, pack=alt)["subtotal"])


def test_markup_rides_the_reduced_subtotal(sample_spec, alt):
    """A markup on the subtotal must not be charged on money that is already
    inside the shares."""
    spec = _shared(sample_spec)
    out = summarize(spec, pack=alt)
    assert out["bid_total"] == pytest.approx(out["subtotal"] + out["markup"])


# --- a cost-detail line whose unit price is a formula ------------------------
def _first_detail_line(spec):
    for item in spec["items"]:
        for cd in item.get("cost_details") or []:
            if cd.get("lines"):
                return item, cd, cd["lines"][0]
    raise AssertionError("the alt sample has no cost-detail line to exercise")


def test_a_formula_unit_price_is_evaluated_not_multiplied_raw(sample_spec, alt):
    """The schema admits a formula here (that is how a share is carried). A
    raw `qty * unit_price` would raise TypeError on the string instead."""
    spec = copy.deepcopy(sample_spec)
    _, _, line = _first_detail_line(spec)
    priced = float(line["unit_price"])
    line["unit_price"] = f"={priced / 2} * 2"
    assert (summarize(spec, pack=alt)["subtotal"]
            == pytest.approx(summarize(sample_spec, pack=alt)["subtotal"]))


def test_a_cross_sheet_share_says_why_it_cannot_price_here(sample_spec, alt):
    """This module prices from the spec alone, so it cannot read another
    sheet's rendered TOTAL. It must say so rather than price the share at a
    default and report a bid that is quietly short."""
    spec = copy.deepcopy(sample_spec)
    _, _, line = _first_detail_line(spec)
    line["unit_price"] = "={ref:3 - HANGER SET!item_total.grand_total}*0.26"
    with pytest.raises(FormulaError) as exc_info:
        summarize(spec, pack=alt)
    assert "cross-sheet ref" in str(exc_info.value)
