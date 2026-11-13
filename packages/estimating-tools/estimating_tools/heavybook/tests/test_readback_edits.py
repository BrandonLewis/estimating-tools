"""Each edit type becomes its op, with its row's ``v`` (spec §3 Field mapping)."""
from __future__ import annotations

import pytest

from estimating_tools.heavybook.tests import _readback as H
from estimating_tools.heavybook.columns import BF, CR, CW


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
    from estimating_tools.exchange.reader import ReadRefused
    with pytest.raises(ReadRefused, match="not a whole number"):
        _read_after(path, H.CR_TAB,
                    lambda ws: {f"{CR.COUNT}{H.cr_row(ws, 'ACTIVITY', 1)}": 1.5})


def test_step_duration(path):
    cs = _read_after(path, H.CR_TAB, lambda ws: {f"{CR.QTY}{H.cr_row(ws, 'STEP', 1)}": 3})
    assert cs.ops == [{"op": "step.update", "ref": 1, "v": "128bba9d35b48338",
                       "fields": {"duration": "3"}}]


@pytest.mark.parametrize("unit", ["DAYS", "HOURS"])
def test_a_step_duration_typed_as_text_is_refused(path, unit):
    # The workbook's Shifts SUMIF skips text, so "4" would count as zero there
    # while BidSheet.ai would count four: refuse it rather than disagree.
    from estimating_tools.exchange.reader import ReadRefused
    with pytest.raises(ReadRefused, match="type the duration as a number"):
        _read_after(path, H.CR_TAB, lambda ws: {
            f"{CR.QTY}{H.cr_row(ws, 'STEP', 1)}": "4",
            f"{CR.UNIT}{H.cr_row(ws, 'STEP', 1)}": unit})

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


def test_a_library_crew_edit_points_at_the_member_row(path):
    """#460: the roster op's ``rows`` and the library-crew note name the
    member row the estimator changed (the summary's row), not the crew's
    header row."""
    wb = H.open_book(path)
    header, finisher = H.cw_row(wb[H.CW_TAB], "CREW", 2), H.cw_row(wb[H.CW_TAB], "MEMBER", 3)
    cs = _read_after(path, H.CW_TAB, lambda ws: {f"{CW.COUNT}{finisher}": 4})
    assert finisher != header
    assert cs.rows == [{"op_index": 0, "sheet": H.CW_TAB, "row": finisher}]
    assert cs.summary == [f"Crews row {finisher}: Pour crew member 'Finisher' count 3 → 4"]
    (note,) = [n for n in cs.notes if "library crew 'Pour crew'" in n]
    assert note.startswith(f"Crews row {finisher}: ")
    assert not any(n.startswith(f"Crews row {header}:") for n in cs.notes)


def test_a_roster_ops_rows_follow_its_summary(path):
    """Every member row the op came from, in sheet order; a removed member has
    no row, so it is ``row: None`` after them -- as the summary lists it."""
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    laborer, oper = H.cw_row(ws, "MEMBER", 1), H.cw_row(ws, "MEMBER", 2)
    ws[f"{CW.COUNT}{laborer}"] = 3
    ws.delete_rows(oper)
    typed = H.type_row(ws, H.cw_row(ws, "CREW_END", parent=1), {CW.CODE: "OPER", CW.COUNT: 2})
    H.save_book(wb, path)
    cs = H.read(path)
    assert [op["op"] for op in cs.ops] == ["crew.update_members"]
    assert cs.rows == [{"op_index": 0, "sheet": H.CW_TAB, "row": laborer},
                       {"op_index": 0, "sheet": H.CW_TAB, "row": typed},
                       {"op_index": 0, "sheet": H.CW_TAB, "row": None}]
    assert [s.split(":")[0] for s in cs.summary] == [
        f"Crews row {laborer}", f"Crews row {typed}", "Crews"]


def test_a_changed_classification_resolves_its_labour_rate(path):
    cs = _read_after(path, H.CW_TAB, lambda ws: {f"{CW.CODE}{H.cw_row(ws, 'MEMBER', 1)}": "oper"})
    members = cs.ops[0]["fields"]["members"]
    assert members[0]["classification"] == "oper" and members[0]["labor_rate_id"] == 1
