"""Tests for the model-QTO -> costs derivation helpers (#205)."""
from __future__ import annotations

import pytest

from estimating_tools.schedule.costload import (
    CodeSpec, derive_costs, item_totals_from_rows, read_item_totals,
    tie_out, validate_costs,
)

# two items; each has a governing code that carries its whole total, plus a
# non-governing code whose cost rides in the governing rate.
SPECS = [
    CodeSpec(code="PS-FTG-CONC", item="Item # 1", quantity=20.0, unit="CY"),
    CodeSpec(code="PS-FTG-REBAR", item="Item # 1", quantity=3000.0, unit="LBS"),
    CodeSpec(code="PS-SADDLE-STL", item="Item # 2", quantity=1500.0, unit="LBS"),
]
GOVERNING = {"Item # 1": "PS-FTG-CONC", "Item # 2": "PS-SADDLE-STL"}
TOTALS = {"Item # 1": 40000.0, "Item # 2": 22500.0}


def test_derive_costs_governing_prices_the_item():
    costs, unrated = derive_costs(SPECS, GOVERNING, TOTALS)
    assert set(costs) == {"PS-FTG-CONC", "PS-SADDLE-STL"}
    assert costs["PS-FTG-CONC"] == {
        "cost": 40000.0, "labor_hours": None,
        "unit_price": 2000.0, "unit": "CY"}        # 40000 / 20
    assert costs["PS-SADDLE-STL"]["unit_price"] == 15.0   # 22500 / 1500
    assert unrated == ["PS-FTG-REBAR"]             # non-governing -> unrated
    validate_costs(costs)                          # emits the contract shape


def test_derive_costs_fails_when_governing_item_absent_from_totals():
    with pytest.raises(ValueError, match="Summary|totals|Item # 2"):
        derive_costs(SPECS, GOVERNING, {"Item # 1": 40000.0})


def test_derive_costs_fails_on_nonpositive_quantity():
    specs = [CodeSpec(code="X", item="Item # 1", quantity=0.0, unit="CY")]
    with pytest.raises(ValueError, match="quantity"):
        derive_costs(specs, {"Item # 1": "X"}, {"Item # 1": 100.0})


def test_tie_out_reconciles_extended_to_priced():
    costs, _ = derive_costs(SPECS, GOVERNING, TOTALS)
    extended, priced = tie_out(costs, SPECS, GOVERNING, TOTALS)
    assert extended == pytest.approx(priced)
    assert priced == pytest.approx(62500.0)        # 40000 + 22500


def test_item_totals_from_rows_filters_item_labels():
    rows = [
        ("Estimate Summary", None),
        ("Item # 1", 40000.0),
        ("Item # 2", 22500.0),
        ("TOTAL", 62500.0),                        # not an "Item #" label
        ("Item # 3", None),                        # no numeric total -> skip
    ]
    out = item_totals_from_rows(rows)
    assert out == {"Item # 1": 40000.0, "Item # 2": 22500.0}


def test_read_item_totals_reads_cached_values(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"], ws["E1"] = "Estimate", None
    ws["A2"], ws["E2"] = "Item # 1", 40000.0       # literal -> data_only reads
    ws["A3"], ws["E3"] = "Item # 2", 22500.0
    p = tmp_path / "est.xlsx"
    wb.save(p)
    assert read_item_totals(str(p)) == {"Item # 1": 40000.0,
                                        "Item # 2": 22500.0}


def test_derive_costs_plural_governing_code_is_item_keyed():
    # one code carries two items -> item-keyed unit_price/unit, summed cost
    specs = [
        CodeSpec(code="CONC", item="Item # 1", quantity=10.0, unit="CY"),
        CodeSpec(code="CONC", item="Item # 2", quantity=20.0, unit="CY"),
    ]
    governing = {"Item # 1": "CONC", "Item # 2": "CONC"}
    totals = {"Item # 1": 5000.0, "Item # 2": 12000.0}
    costs, unrated = derive_costs(specs, governing, totals)
    assert unrated == []
    rec = costs["CONC"]
    assert rec["cost"] == pytest.approx(17000.0)               # summed
    assert rec["unit_price"] == {"Item # 1": 500.0, "Item # 2": 600.0}
    assert rec["unit"] == {"Item # 1": "CY", "Item # 2": "CY"}
    validate_costs(costs)                                      # item-keyed OK
    extended, priced = tie_out(costs, specs, governing, totals)
    assert extended == pytest.approx(priced) == pytest.approx(17000.0)


def test_derive_costs_fails_when_governing_code_has_no_spec():
    # governing names a code absent from specs -> item silently dropped; refuse
    specs = [CodeSpec(code="A", item="Item # 1", quantity=1.0, unit="EA")]
    with pytest.raises(ValueError, match="no matching CodeSpec"):
        derive_costs(specs, {"Item # 1": "GHOST"}, {"Item # 1": 100.0})


def test_tie_out_raises_on_missing_governing_total():
    costs = {"A": {"cost": 100.0, "labor_hours": None, "unit_price": 50.0,
                   "unit": "EA"}}
    specs = [CodeSpec(code="A", item="Item # 1", quantity=2.0, unit="EA")]
    governing = {"Item # 1": "A", "Item # 2": "A"}    # Item # 2 not in totals
    with pytest.raises(ValueError, match="missing from totals|not priced"):
        tie_out(costs, specs, governing, {"Item # 1": 100.0})


def test_read_item_totals_releases_the_file(tmp_path):
    # the workbook handle must be closed so the file can be replaced/removed
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "Summary"
    wb.active["A2"], wb.active["E2"] = "Item # 1", 100.0
    p = tmp_path / "est.xlsx"
    wb.save(p)
    read_item_totals(str(p))
    p.unlink()                        # would raise PermissionError if still open
    assert not p.exists()


def test_read_item_totals_fails_loud_when_uncached(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A2"], ws["E2"] = "Item # 1", "=1+1"        # formula -> data_only None
    p = tmp_path / "est.xlsx"
    wb.save(p)
    with pytest.raises(ValueError, match="recalc|evaluat|cached"):
        read_item_totals(str(p))
