import pytest

from estimating_tools.assemblies.excel import (
    build_assembly_library, build_assembly_library_from_excel, read_assembly_rows,
)
from estimating_tools.assemblies.model import CanonicalAssemblyLibrary


def _identity_rows():
    # columns named exactly as the canonical fields (identity mapping)
    return [
        {"assembly": "CIP wall", "assembly_type": "concrete", "cost_code": "03-300",
         "assembly_description": "CIP wall", "component_type": "labor", "component": "Form/pour",
         "quantity": 8, "unit": "HR", "unit_cost": 65, "trade": "carpenter", "component_description": ""},
        {"assembly": "CIP wall", "assembly_type": "concrete", "cost_code": "03-300",
         "assembly_description": "CIP wall", "component_type": "material", "component": "Ready-mix",
         "quantity": 1, "unit": "CY", "unit_cost": 145, "trade": "", "component_description": ""},
    ]


def test_identity_mapping_groups_into_one_assembly_with_two_components():
    lib = build_assembly_library(_identity_rows())
    assert isinstance(lib, CanonicalAssemblyLibrary)
    assert len(lib.assemblies) == 1
    a = lib.assemblies[0]
    assert a.name == "CIP wall" and a.assembly_type == "concrete" and a.cost_code == "03-300"
    assert [(c.component_type, c.name, c.quantity, c.unit, c.unit_cost) for c in a.components] == [
        ("labor", "Form/pour", 8.0, "HR", 65.0),
        ("material", "Ready-mix", 1.0, "CY", 145.0),
    ]


def test_custom_mapping_reads_org_columns():
    rows = [
        {"Assembly Name": "Striping", "Kind": "paving", "Crew Type": "Labor", "Item": "Stripe",
         "Qty": 2, "UoM": "LS", "Unit $": 500},
    ]
    mapping = {"assembly": "Assembly Name", "assembly_type": "Kind", "component_type": "Crew Type",
               "component": "Item", "quantity": "Qty", "unit": "UoM", "unit_cost": "Unit $"}
    lib = build_assembly_library(rows, mapping)
    a = lib.assemblies[0]
    assert a.name == "Striping" and a.assembly_type == "paving"
    c = a.components[0]
    assert c.component_type == "labor" and c.name == "Stripe" and c.quantity == 2.0
    assert c.unit == "LS" and c.unit_cost == 500.0


def test_component_type_aliases_normalized():
    rows = [
        {"assembly": "A", "component_type": "lab", "component": "a"},
        {"assembly": "A", "component_type": "labour", "component": "b"},
        {"assembly": "A", "component_type": "MAT", "component": "c"},
        {"assembly": "A", "component_type": "matl", "component": "d"},
        {"assembly": "A", "component_type": "equip", "component": "e"},
        {"assembly": "A", "component_type": "eqp", "component": "f"},
        {"assembly": "A", "component_type": "Sub", "component": "g"},
    ]
    types = [c.component_type for c in build_assembly_library(rows).assemblies[0].components]
    assert types == ["labor", "labor", "material", "material", "equipment", "equipment", "subcontractor"]


def test_unrecognized_component_type_raises():
    rows = [{"assembly": "Foo", "component_type": "widget", "component": "x"}]
    with pytest.raises(ValueError, match=r"widget.*Foo|Foo.*widget"):
        build_assembly_library(rows)


def test_missing_required_column_raises():
    # no 'component' column at all -> required-field error
    rows = [{"assembly": "A", "component_type": "labor", "name_typo": "x"}]
    with pytest.raises(ValueError):
        build_assembly_library(rows)


def test_blank_component_value_on_named_row_raises():
    # the 'component' column exists but a non-skipped row leaves it blank/whitespace
    rows = [{"assembly": "Foo", "component_type": "labor", "component": "  "}]
    with pytest.raises(ValueError, match=r"component.*Foo|Foo.*component"):
        build_assembly_library(rows)


def test_blank_rows_and_defaults():
    rows = [
        {"assembly": "", "component_type": "labor", "component": "skip-me"},   # blank assembly -> skipped
        {"assembly": "A", "component_type": "labor", "component": "Crew"},      # no quantity/unit_cost
    ]
    lib = build_assembly_library(rows)
    assert [a.name for a in lib.assemblies] == ["A"]
    c = lib.assemblies[0].components[0]
    assert c.quantity == 1.0 and c.unit_cost is None and c.unit == ""


def test_empty_rows_yield_empty_library():
    assert build_assembly_library([]).assemblies == []


def test_read_assembly_rows_and_from_excel_roundtrip(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["assembly", "component_type", "component", "quantity", "unit_cost"])
    ws.append(["CIP wall", "labor", "Form/pour", 8, 65])
    ws.append(["CIP wall", "material", "Ready-mix", 1, 145])
    path = tmp_path / "lib.xlsx"
    wb.save(path)

    rows = read_assembly_rows(path)
    assert rows[0]["assembly"] == "CIP wall" and rows[0]["component_type"] == "labor"

    lib = build_assembly_library_from_excel(path)
    assert len(lib.assemblies) == 1 and len(lib.assemblies[0].components) == 2


def test_blank_cost_code_becomes_none():
    rows = [{"assembly": "A", "cost_code": "", "component_type": "labor", "component": "x"}]
    a = build_assembly_library(rows).assemblies[0]
    assert a.cost_code is None


def test_rate_ref_read_into_component_and_blank_becomes_none():
    rows = [
        {"assembly": "A", "component_type": "labor", "component": "Crew",
         "rate_ref": "carpenter-journeyman"},
        {"assembly": "A", "component_type": "material", "component": "Rebar",
         "rate_ref": ""},   # blank -> None
    ]
    comps = build_assembly_library(rows).assemblies[0].components
    assert comps[0].rate_ref == "carpenter-journeyman"
    assert comps[1].rate_ref is None


def test_rate_ref_custom_mapping():
    rows = [{"Assembly Name": "Striping", "Crew Type": "Labor", "Item": "Stripe",
             "Rate Key": "striper-op"}]
    mapping = {"assembly": "Assembly Name", "component_type": "Crew Type",
               "component": "Item", "rate_ref": "Rate Key"}
    c = build_assembly_library(rows, mapping).assemblies[0].components[0]
    assert c.rate_ref == "striper-op"


def test_imported_rate_ref_flows_into_push_plan_resolution():
    # end-to-end: a spreadsheet rate_ref on a labor component resolves in the push plan
    from estimating_tools.assemblies.plan import plan_assembly_push

    rows = [{"assembly": "A", "component_type": "labor", "component": "Crew",
             "rate_ref": "carpenter-journeyman"}]
    lib = build_assembly_library(rows)
    plan = plan_assembly_push(lib, org_id=7)
    comp = plan.assemblies[0]["components"][0]
    assert comp["rate_resolution"] == {"kind": "labor", "key": "carpenter-journeyman"}
