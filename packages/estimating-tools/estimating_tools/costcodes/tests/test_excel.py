import pytest

from estimating_tools.costcodes.excel import (
    build_cost_code_system, build_cost_code_system_from_excel, read_costcode_rows,
)
from estimating_tools.costcodes.model import CanonicalCostCodeSystem


def _codes(sys):
    return [a.code for a in sys.activity_codes]


def test_identity_mapping_builds_system_with_codes_and_types():
    rows = [
        {"code": "02", "description": "Bridge", "cost_type": "L", "cost_type_name": "Labor"},
        {"code": "02-110", "description": "Form Footings", "cost_type": "L",
         "parent_code": "02", "default_unit": "MH"},
        {"code": "02-200", "description": "Rebar", "cost_type": "M", "cost_type_name": "Material",
         "parent_code": "02"},
    ]
    sys = build_cost_code_system(rows, system_name="Std Codes 2026", version="2026.1")
    assert isinstance(sys, CanonicalCostCodeSystem)
    assert sys.name == "Std Codes 2026" and sys.version == "2026.1"
    # cost types derived in first-seen order, names honored
    assert [(c.code, c.name) for c in sys.cost_types] == [("L", "Labor"), ("M", "Material")]
    # all three codes present; parent before children
    assert set(_codes(sys)) == {"02", "02-110", "02-200"}
    assert _codes(sys).index("02") < _codes(sys).index("02-110")
    assert _codes(sys).index("02") < _codes(sys).index("02-200")
    child = next(a for a in sys.activity_codes if a.code == "02-110")
    assert child.parent_code == "02" and child.cost_type_code == "L" and child.default_unit == "MH"


def test_custom_mapping_reads_org_columns():
    rows = [{"Code": "01-100", "Desc": "Mobilization", "Type": "L", "Parent": ""}]
    mapping = {"code": "Code", "description": "Desc", "cost_type": "Type", "parent_code": "Parent"}
    sys = build_cost_code_system(rows, system_name="S", mapping=mapping)
    a = sys.activity_codes[0]
    assert a.code == "01-100" and a.description == "Mobilization" and a.cost_type_code == "L"
    assert a.parent_code == ""


def test_child_before_parent_in_sheet_is_reordered():
    # child listed FIRST; must come out AFTER its parent
    rows = [
        {"code": "02-110", "parent_code": "02"},
        {"code": "02", "parent_code": ""},
    ]
    sys = build_cost_code_system(rows, system_name="S")
    assert _codes(sys).index("02") < _codes(sys).index("02-110")


def test_missing_parent_raises():
    with pytest.raises(ValueError, match=r"02-110|parent"):
        build_cost_code_system([{"code": "02-110", "parent_code": "99"}], system_name="S")


def test_duplicate_code_raises():
    with pytest.raises(ValueError, match=r"duplicate|02-110"):
        build_cost_code_system(
            [{"code": "02-110"}, {"code": "02-110"}], system_name="S")


def test_self_parent_raises():
    with pytest.raises(ValueError, match=r"02-110|itself|self"):
        build_cost_code_system([{"code": "02-110", "parent_code": "02-110"}], system_name="S")


def test_cycle_raises():
    rows = [
        {"code": "A", "parent_code": "B"},
        {"code": "B", "parent_code": "A"},
    ]
    with pytest.raises(ValueError, match=r"cycle|A|B"):
        build_cost_code_system(rows, system_name="S")


def test_multi_node_cycle_raises():
    # a 3-node cycle A->B->C->A must also raise (not just the 2-node case)
    rows = [
        {"code": "A", "parent_code": "B"},
        {"code": "B", "parent_code": "C"},
        {"code": "C", "parent_code": "A"},
    ]
    with pytest.raises(ValueError, match=r"cycle|A|B|C"):
        build_cost_code_system(rows, system_name="S")


def test_cycle_message_reports_only_cycle_nodes_not_prefix():
    # D feeds INTO a cycle A->B->C->A but is not itself part of it; the error names the
    # cycle nodes, not the prefix node D.
    rows = [
        {"code": "D", "parent_code": "A"},
        {"code": "A", "parent_code": "B"},
        {"code": "B", "parent_code": "C"},
        {"code": "C", "parent_code": "A"},
    ]
    with pytest.raises(ValueError) as exc:
        build_cost_code_system(rows, system_name="S")
    msg = str(exc.value)
    assert "cycle" in msg and "A" in msg and "B" in msg and "C" in msg
    assert "'D'" not in msg


def test_forest_multiple_roots_dfs_order():
    # two roots A and B; C is a child of A. A's whole subtree must come out before B
    # (the topo sort exhausts each root's subtree before the next root).
    rows = [
        {"code": "A", "parent_code": ""},
        {"code": "B", "parent_code": ""},
        {"code": "C", "parent_code": "A"},
    ]
    sys = build_cost_code_system(rows, system_name="S")
    assert _codes(sys) == ["A", "C", "B"]


def test_blank_cost_type_name_defaults_to_code_and_blank_type_no_costtype():
    rows = [
        {"code": "A", "cost_type": "E"},                 # no cost_type_name -> name == code
        {"code": "B"},                                   # blank cost_type -> no cost type, cost_type_code ""
    ]
    sys = build_cost_code_system(rows, system_name="S")
    assert [(c.code, c.name) for c in sys.cost_types] == [("E", "E")]
    b = next(a for a in sys.activity_codes if a.code == "B")
    assert b.cost_type_code == ""


def test_sort_order_and_is_active_parse():
    rows = [
        {"code": "A", "sort_order": "5", "is_active": "no"},
        {"code": "B"},                                   # blank -> sort_order 0, is_active True
        {"code": "C", "sort_order": "5.0", "is_active": "false"},   # float cell -> 5; falsy -> False
        {"code": "D", "sort_order": "abc", "is_active": "0"},       # non-numeric -> 0; "0" -> False
        {"code": "E", "is_active": "n"},                            # "n" -> False
    ]
    sys = build_cost_code_system(rows, system_name="S")
    by = {x.code: x for x in sys.activity_codes}
    assert by["A"].sort_order == 5 and by["A"].is_active is False
    assert by["B"].sort_order == 0 and by["B"].is_active is True
    assert by["C"].sort_order == 5 and by["C"].is_active is False
    assert by["D"].sort_order == 0 and by["D"].is_active is False
    assert by["E"].is_active is False


def test_required_code_and_system_name_validation():
    with pytest.raises(ValueError):
        build_cost_code_system([{"code_typo": "A"}], system_name="S")   # no 'code' column
    with pytest.raises(ValueError):
        build_cost_code_system([{"code": "A"}], system_name="  ")       # blank system_name


def test_blank_code_row_skipped_and_empty_is_empty():
    rows = [{"code": ""}, {"code": "A"}]
    sys = build_cost_code_system(rows, system_name="S")
    assert _codes(sys) == ["A"]
    empty = build_cost_code_system([], system_name="S")
    assert empty.activity_codes == [] and empty.cost_types == []


def test_read_costcode_rows_and_from_excel_roundtrip(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["code", "description", "cost_type", "parent_code"])
    ws.append(["02", "Bridge", "L", ""])
    ws.append(["02-110", "Form Footings", "L", "02"])
    path = tmp_path / "codes.xlsx"
    wb.save(path)

    rows = read_costcode_rows(path)
    assert rows[0]["code"] == "02" and rows[1]["parent_code"] == "02"

    sys = build_cost_code_system_from_excel(path, system_name="S")
    assert _codes(sys).index("02") < _codes(sys).index("02-110")
    assert [c.code for c in sys.cost_types] == ["L"]


def test_builder_numeric_stub_reproduces_tree_and_tags():
    rows = [
        {"code": "02-000", "description": "Bridge Conc", "structure_tags": "Bridge|CIP"},
        {"code": "02-100", "description": "Footings"},
        {"code": "02-110", "description": "Form/Strip"},
    ]
    m = {f: f for f in ("code", "description", "structure_tags")}
    sys = build_cost_code_system(
        rows, system_name="Acme", mapping=m,
        parent_strategy="numeric_stub", composition="composed",
        source_system="Acme", edition="2026.1",
    )
    assert sys.composition == "composed"
    assert sys.source_system == "Acme" and sys.edition == "2026.1"
    by = {a.code: a for a in sys.activity_codes}
    assert by["02-110"].parent_code == "02-100"
    assert by["02-100"].parent_code == "02-000"
    assert by["02-000"].parent_code == ""
    assert by["02-000"].structure_tags == ["Bridge", "CIP"]
    assert by["02-110"].source_code == "02-110"


def test_builder_segment_truncate_monolithic_masterformat():
    rows = [{"code": "03"}, {"code": "03 30 00"}, {"code": "03 30 00.13"}]
    m = {"code": "code"}
    sys = build_cost_code_system(
        rows, system_name="MF", mapping=m,
        parent_strategy="segment_truncate", composition="monolithic",
    )
    assert sys.composition == "monolithic"
    by = {a.code: a for a in sys.activity_codes}
    assert by["03 30 00.13"].parent_code == "03 30 00"
    assert by["03 30 00"].parent_code == "03"


def test_builder_default_strategy_is_explicit_column_backcompat():
    rows = [{"code": "A", "parent_code": ""}, {"code": "B", "parent_code": "A"}]
    m = {"code": "code", "parent_code": "parent_code"}
    sys = build_cost_code_system(rows, system_name="X", mapping=m)
    by = {a.code: a for a in sys.activity_codes}
    assert by["B"].parent_code == "A"


def test_builder_stamps_level_from_depth():
    rows = [{"code": "02-000"}, {"code": "02-100"}, {"code": "02-110"}, {"code": "02-111"}]
    m = {"code": "code"}
    sys = build_cost_code_system(rows, system_name="D", mapping=m, parent_strategy="numeric_stub")
    by = {a.code: a for a in sys.activity_codes}
    assert by["02-000"].level == 0
    assert by["02-100"].level == 1
    assert by["02-110"].level == 2
    assert by["02-111"].level == 3
