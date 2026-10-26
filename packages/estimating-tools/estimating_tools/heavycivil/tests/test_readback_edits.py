"""Each edit type becomes its op, with its row's ``v`` (spec §3 Field mapping)."""
from __future__ import annotations

import pytest

from estimating_tools.heavycivil.tests import _readback as H
from estimating_tools.heavycivil.columns import BF, CR, CW


@pytest.fixture
def path(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")


def _read_after(path, sheet, cells):
    wb = H.open_book(path)
    ws = wb[sheet]
    for addr, value in cells(ws).items():
        ws[addr] = value
    H.save_book(wb, path)
    return H.read(path)


def _bf(ws, item_id):
    return H.find_row(ws, "ITEM_BID", item_id, kind_col=BF.KIND, id_col=BF.ID)


def test_round_trip_reads_no_ops(path):
    cs = H.read(path)
    assert cs.ops == [] and cs.rows == [] and cs.summary == [] and cs.notes == []
    assert cs.estimate_id == 1 and cs.estimate_v == H.fixture_doc()["estimate"]["v"]


def test_round_trip_with_rate_links_reads_no_ops(tmp_path):
    path = H.build_book(H.linked_doc(), tmp_path / "linked.xlsx")
    assert H.read(path).ops == []


def test_markup(path):
    cs = _read_after(path, H.BF_TAB, lambda ws: {"C4": 12.5})
    assert cs.ops == [{"op": "estimate.update", "ref": 1, "v": "ac6cc8eec0e04323",
                       "fields": {"markup_percentage": "12.5"}}]
    assert cs.rows == [{"op_index": 0, "sheet": H.BF_TAB, "row": 4}]
    assert cs.summary == [f"{H.BF_TAB} row 4: estimate markup_percentage 10 → 12.5"]


def test_item_fields_from_both_sheets_merge_into_one_op(path):
    wb = H.open_book(path)
    cr, bf = wb[H.CR_TAB], wb[H.BF_TAB]
    cr[f"{CR.QTY}{H.cr_row(cr, 'ITEM', 1)}"] = 120
    bf[f"{BF.SCOPE}{_bf(bf, 1)}"] = "Excluded"
    H.save_book(wb, path)
    cs = H.read(path)
    assert cs.ops == [{"op": "item.update", "ref": 1, "v": "973354cc8099ae7e",
                       "fields": {"quantity_override": "120", "scope": "excluded"}}]
    assert {r["sheet"] for r in cs.rows} == {H.CR_TAB, H.BF_TAB}


def test_element_quantity_override(path):
    cs = _read_after(path, H.CR_TAB,
                     lambda ws: {f"{CR.QTY}{H.cr_row(ws, 'ELEMENT_QTY', 2)}": 60})
    assert cs.ops == [{"op": "element.set_quantity", "ref": 2, "v": "163fe7e03f4fa7a5",
                       "fields": {"key": "concrete_cy", "override_value": "60"}}]


def test_activity_inputs(path):
    cs = _read_after(path, H.CR_TAB, lambda ws: {
        f"{CR.DESC}{H.cr_row(ws, 'ACTIVITY', 2)}": "Walls east",
        f"{CR.PROD}{H.cr_row(ws, 'ACTIVITY', 2)}": 2,
        f"{CR.PUNIT}{H.cr_row(ws, 'ACTIVITY', 2)}": "hours",
        f"{CR.COUNT}{H.cr_row(ws, 'ACTIVITY', 2)}": 3})
    assert cs.ops == [{"op": "activity.update", "ref": 2, "v": "b96859bc0ac1b1c5",
                       "fields": {"name": "Walls east", "production_rate": "2",
                                  "production_unit": "HOURS", "count": 3}}]


def test_unstepped_shifts_are_an_input(path):
    cs = _read_after(path, H.CR_TAB,
                     lambda ws: {f"{CR.SHIFTS}{H.cr_row(ws, 'ACTIVITY', 1)}": 4})
    assert cs.ops == [{"op": "activity.update", "ref": 1, "v": "e75e9841d0ce53e9",
                       "fields": {"duration_shifts": "4"}}]


def test_a_count_must_be_whole(path):
    from estimating_tools.heavycivil.readback import ReadRefused
    with pytest.raises(ReadRefused, match="not a whole number"):
        _read_after(path, H.CR_TAB,
                    lambda ws: {f"{CR.COUNT}{H.cr_row(ws, 'ACTIVITY', 1)}": 1.5})


def test_step_duration(path):
    cs = _read_after(path, H.CR_TAB, lambda ws: {f"{CR.QTY}{H.cr_row(ws, 'STEP', 1)}": 3})
    assert cs.ops == [{"op": "step.update", "ref": 1, "v": "128bba9d35b48338",
                       "fields": {"duration": "3"}}]


def test_resource_inputs(path):
    cs = _read_after(path, H.CR_TAB, lambda ws: {
        f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 2)}": 3,
        f"{CR.BURD}{H.cr_row(ws, 'RESOURCE', 2)}": None,
        f"{CR.BINC}{H.cr_row(ws, 'RESOURCE', 2)}": "Y",
        f"{CR.BASIS}{H.cr_row(ws, 'RESOURCE', 2)}": "Flat"})
    assert cs.ops == [{"op": "resource.update", "ref": 2, "v": "f1768f35b95a7a77",
                       "fields": {"quantity": "3", "labor_cost_basis": "flat",
                                  "burden_percentage": None, "includes_burden": True}}]


def test_member_count_sends_the_whole_roster(path):
    cs = _read_after(path, H.CW_TAB, lambda ws: {f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 1)}": 3})
    assert cs.ops == [{"op": "crew.update_members", "ref": 1, "v": "5e68b40e2a6f0914",
                       "fields": {"members": [
                           {"classification": "Laborer", "count": "3", "labor_rate_id": None,
                            "hourly_rate_override": "50", "sort_order": 0},
                           {"classification": "OPER", "count": "1", "labor_rate_id": 1,
                            "hourly_rate_override": None, "sort_order": 0}]}}]


def test_a_library_crew_edit_names_the_copy(path):
    cs = _read_after(path, H.CW_TAB,
                     lambda ws: {f"{CW.OVERRIDE}{H.cw_row(ws, 'MEMBER', 3)}": 65})
    assert [(op["op"], op["ref"]) for op in cs.ops] == [("crew.update_members", 2)]
    assert any("library crew 'Pour crew'" in n and "copies it into this estimate" in n
               for n in cs.notes)


def test_a_changed_classification_resolves_its_labour_rate(path):
    cs = _read_after(path, H.CW_TAB, lambda ws: {f"{CW.CODE}{H.cw_row(ws, 'MEMBER', 1)}": "oper"})
    members = cs.ops[0]["fields"]["members"]
    assert members[0]["classification"] == "oper" and members[0]["labor_rate_id"] == 1
