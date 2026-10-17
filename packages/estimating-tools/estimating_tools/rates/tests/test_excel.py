import pytest

from estimating_tools.rates.excel import (
    build_rate_library, build_rate_library_from_excel, read_rate_rows,
)
from estimating_tools.rates.model import CanonicalRateLibrary


def test_identity_mapping_routes_three_types():
    rows = [
        {"rate_type": "labor", "name": "CARP", "rate": 45, "burden_percentage": 40,
         "trade": "Carpenter", "is_union": "yes", "region": "Bay Area"},
        {"rate_type": "equipment", "name": "EXCAVATOR", "rate": 120,
         "description": "CAT 320", "includes_operator": "x"},
        {"rate_type": "material", "name": "Concrete 3000 PSI", "rate": 145,
         "unit": "CY", "category": "CONCRETE", "supplier": "Acme Ready-Mix"},
    ]
    lib = build_rate_library(rows)
    assert isinstance(lib, CanonicalRateLibrary)
    assert len(lib.labor_rates) == 1 and len(lib.equipment_rates) == 1 and len(lib.material_costs) == 1
    lr = lib.labor_rates[0]
    assert lr.classification == "CARP" and lr.base_hourly_rate == 45.0
    assert lr.burden_percentage == 40.0 and lr.trade == "Carpenter" and lr.is_union is True
    assert lr.region == "Bay Area"
    er = lib.equipment_rates[0]
    assert er.equipment_type == "EXCAVATOR" and er.hourly_rate == 120.0
    assert er.description == "CAT 320" and er.includes_operator is True
    mc = lib.material_costs[0]
    assert mc.material_name == "Concrete 3000 PSI" and mc.unit_cost == 145.0
    assert mc.unit == "CY" and mc.category == "CONCRETE" and mc.supplier == "Acme Ready-Mix"


def test_custom_mapping_reads_org_columns():
    rows = [{"Type": "Labor", "Classification": "OPER", "Base $/hr": "52.50", "Burden %": "38"}]
    mapping = {"rate_type": "Type", "name": "Classification", "rate": "Base $/hr",
               "burden_percentage": "Burden %"}
    lib = build_rate_library(rows, mapping)
    lr = lib.labor_rates[0]
    assert lr.classification == "OPER" and lr.base_hourly_rate == 52.5 and lr.burden_percentage == 38.0


def test_rate_type_aliases_and_unknown_raises():
    rows = [
        {"rate_type": "LAB", "name": "A", "rate": 30},
        {"rate_type": "equip", "name": "B", "rate": 40},
        {"rate_type": "matl", "name": "C", "rate": 5},
    ]
    lib = build_rate_library(rows)
    assert len(lib.labor_rates) == 1 and len(lib.equipment_rates) == 1 and len(lib.material_costs) == 1
    with pytest.raises(ValueError, match=r"fuel|D"):
        build_rate_library([{"rate_type": "fuel", "name": "D", "rate": 9}])


def test_burden_default_and_booleans():
    lib = build_rate_library([{"rate_type": "labor", "name": "LAB", "rate": 30}])
    assert lib.labor_rates[0].burden_percentage == 35.0 and lib.labor_rates[0].is_union is False
    eq = build_rate_library([{"rate_type": "equipment", "name": "CRANE", "rate": 200}])
    assert eq.equipment_rates[0].includes_operator is False


def test_non_numeric_rate_raises():
    with pytest.raises(ValueError, match=r"rate|CARP"):
        build_rate_library([{"rate_type": "labor", "name": "CARP", "rate": "N/A"}])


def test_uppercase_truthy_and_nonnumeric_burden():
    # truthy normalization is case-insensitive (lowercased before the set check)
    lib = build_rate_library([
        {"rate_type": "labor", "name": "CARP", "rate": 45, "is_union": "YES"},
        {"rate_type": "equipment", "name": "CRANE", "rate": 200, "includes_operator": "True"},
    ])
    assert lib.labor_rates[0].is_union is True
    assert lib.equipment_rates[0].includes_operator is True
    # a non-blank but non-numeric burden_percentage is reported (not silently defaulted)
    with pytest.raises(ValueError, match=r"burden_percentage|CARP"):
        build_rate_library([{"rate_type": "labor", "name": "CARP", "rate": 45,
                             "burden_percentage": "N/A"}])


def test_blank_name_raises():
    with pytest.raises(ValueError, match=r"name|labor"):
        build_rate_library([{"rate_type": "labor", "name": "  ", "rate": 30}])


def test_missing_required_column_raises():
    # no 'rate' column at all -> required-field error
    with pytest.raises(ValueError, match=r"rate|cost_typo"):
        build_rate_library([{"rate_type": "labor", "name": "CARP", "cost_typo": 30}])


def test_blank_rate_type_row_skipped_and_empty_is_empty():
    rows = [
        {"rate_type": "", "name": "skip", "rate": 1},
        {"rate_type": "labor", "name": "CARP", "rate": 45},
    ]
    lib = build_rate_library(rows)
    assert [r.classification for r in lib.labor_rates] == ["CARP"]
    empty = build_rate_library([])
    assert empty.labor_rates == [] and empty.equipment_rates == [] and empty.material_costs == []


def test_read_rate_rows_and_from_excel_roundtrip(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["rate_type", "name", "rate", "unit"])
    ws.append(["material", "Rebar #4", 0.85, "LF"])
    ws.append(["labor", "CARP", 45, ""])
    path = tmp_path / "rates.xlsx"
    wb.save(path)

    rows = read_rate_rows(path)
    assert rows[0]["rate_type"] == "material" and rows[0]["name"] == "Rebar #4"

    lib = build_rate_library_from_excel(path)
    assert len(lib.material_costs) == 1 and len(lib.labor_rates) == 1
    assert lib.material_costs[0].unit == "LF"


def test_fringe_is_read_for_labor_rates():
    rows = [{"rate_type": "labor", "name": "Pipelayer", "rate": 48.10,
             "burden_percentage": 32, "fringe_hourly": 18.40}]
    (lr,) = build_rate_library(rows).labor_rates
    assert lr.fringe_hourly == 18.40


def test_fringe_defaults_to_zero():
    rows = [{"rate_type": "labor", "name": "Laborer", "rate": 61}]
    (lr,) = build_rate_library(rows).labor_rates
    assert lr.fringe_hourly == 0.0


def test_fringe_maps_from_an_org_column():
    rows = [{"Type": "labor", "Class": "Pipelayer", "Wage": 48.10, "H&W+Pension": 18.40}]
    mapping = {"rate_type": "Type", "name": "Class", "rate": "Wage",
               "fringe_hourly": "H&W+Pension"}
    (lr,) = build_rate_library(rows, mapping).labor_rates
    assert lr.fringe_hourly == 18.40
