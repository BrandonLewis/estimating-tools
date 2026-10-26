"""New, copied, pasted, cut and deleted rows (spec §2 Classify, Copies and pastes; §3 Moves)."""
from __future__ import annotations

import pytest

from estimating_tools.heavycivil.tests import _readback as H
from estimating_tools.heavycivil.columns import CR, CW
from estimating_tools.heavycivil.readback import ReadRefused


def _book(tmp_path, doc=None):
    return H.build_book(doc or H.fixture_doc(), tmp_path / "book.xlsx")


def _edit(path, fn, sheet=H.CR_TAB):
    wb = H.open_book(path)
    fn(wb[sheet])
    H.save_book(wb, path)


def _refused(path):
    with pytest.raises(ReadRefused) as exc:
        H.read(path)
    return [p.message for p in exc.value.problems]


def _block(ws, first_activity, last_activity=None):
    """(ACTIVITY row of ``first_activity``, END row of ``last_activity``)."""
    first = H.cr_row(ws, "ACTIVITY", first_activity)
    return first, H.cr_row(ws, "END", parent=last_activity or first_activity, start=first)


def _paste(ws, activity_id, values):
    """A resource row as if pasted from another book: resource 1's row (its
    formulas, type and rate link) with a foreign id, typed over with
    ``values``, above ``activity_id``'s END marker."""
    r = H.cr_row(ws, "RESOURCE", 1)
    new = H.insert_copies(ws, r, r, H.block_end(ws, activity_id))
    ws[f"{CR.ID}{new}"] = 9999
    ws[f"{CR.V}{new}"] = "0123456789abcdef"
    for letter, value in values.items():
        ws[f"{letter}{new}"] = value
    return new


# -- copies and pastes -----------------------------------------------------------

def test_a_same_book_copy_changed_only_in_quantity_keeps_its_rate_link(tmp_path):
    path = _book(tmp_path, H.linked_doc())

    def copy(ws):
        r = H.cr_row(ws, "RESOURCE", 1)
        new = H.insert_copies(ws, r, r, H.block_end(ws, 1))
        ws[f"{CR.QTY}{new}"] = 40
    _edit(path, copy)
    cs = H.read(path)
    assert cs.ops == [{"op": "resource.create", "ref": "new:r1", "fields": {
        "activity_id": 1, "name": "CAT 336", "quantity": "40", "unit_cost": "185",
        "component_type": "equipment", "labor_cost_basis": "production",
        "includes_burden": False, "equipment_rate_id": 7}}]


@pytest.mark.parametrize("letter, value", [(CR.UCOST, 190), (CR.DESC, "CAT 340"),
                                           (CR.TYPE, "other"), (CR.UNIT, "HR")])
def test_an_edited_copy_is_created_plain(tmp_path, letter, value):
    path = _book(tmp_path, H.linked_doc())

    def copy(ws):
        r = H.cr_row(ws, "RESOURCE", 1)
        new = H.insert_copies(ws, r, r, H.block_end(ws, 1))
        ws[f"{letter}{new}"] = value
    _edit(path, copy)
    (op,) = H.read(path).ops
    assert op["op"] == "resource.create" and "equipment_rate_id" not in op["fields"]
    assert "unit_cost" in op["fields"]


def test_a_linked_paste_from_another_book_is_sent_without_unit_cost(tmp_path):
    path = _book(tmp_path, H.linked_doc())
    _edit(path, lambda ws: _paste(ws, 2, {CR.DESC: "Pump", CR.QTY: 2, CR.UCOST: 80}))
    cs = H.read(path)
    assert cs.ops == [{"op": "resource.create", "ref": "new:r1", "fields": {
        "activity_id": 2, "name": "Pump", "quantity": "2", "component_type": "equipment",
        "labor_cost_basis": "production", "includes_burden": False,
        "equipment_rate_id": 7}}]
    assert any("today's library rate" in n for n in cs.notes)


def test_an_unlinked_paste_is_created_plain(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: _paste(ws, 2, {CR.DESC: "Pump", CR.QTY: 2, CR.UCOST: 80}))
    (op,) = H.read(path).ops
    assert op["fields"]["unit_cost"] == "80"
    assert not {"labor_rate_id", "equipment_rate_id", "material_cost_id"} & set(op["fields"])


def test_a_pasted_non_resource_row_is_refused(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.cr_row(ws, "START", parent=4), {
        CR.KIND: "STEP", CR.ID: 999, CR.PARENT: 4, CR.DESC: "Strip", CR.QTY: 1}))
    assert "only resource rows can be pasted in from another workbook" in _refused(path)


def test_the_original_of_a_duplicate_stays_under_its_baseline_activity(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        r = H.cr_row(ws, "RESOURCE", 9)                   # activity 8, near the bottom
        H.insert_copies(ws, r, r, H.block_end(ws, 1))     # into activity 1, above it
    _edit(path, copy)
    cs = H.read(path)
    assert [(op["op"], op["ref"], op["fields"]["activity_id"]) for op in cs.ops] == [
        ("resource.create", "new:r1", 1)]


# -- typed rows ------------------------------------------------------------------

def test_a_typed_resource_is_created_and_named_as_not_priced_live(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.block_end(ws, 5), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "Equipment"}))
    cs = H.read(path)
    assert cs.ops == [{"op": "resource.create", "ref": "new:r1", "fields": {
        "activity_id": 5, "name": "Pump", "quantity": "1", "unit_cost": "250",
        "component_type": "equipment"}}]
    assert any("not priced live" in n and "'Pump'" in n for n in cs.notes)


def test_a_typed_resource_needs_a_type(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.block_end(ws, 5), {CR.DESC: "Pump", CR.QTY: 1}))
    assert any("needs a Type" in m for m in _refused(path))


def test_a_typed_step_between_steps_and_start(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.cr_row(ws, "START", parent=4), {
        CR.DESC: "Strip", CR.QTY: 4, CR.UNIT: "hours"}))
    cs = H.read(path)
    assert cs.ops == [{"op": "step.add", "ref": "new:s1", "fields": {
        "activity_id": 4, "name": "Strip", "duration": "4", "duration_unit": "HOURS"}}]


def test_a_typed_member(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.cw_row(ws, "CREW_END", parent=1), {
        CW.CODE: "oper", CW.COUNT: 2}), sheet=H.CW_TAB)
    (op,) = H.read(path).ops
    assert op["op"] == "crew.update_members" and op["ref"] == 1
    assert op["fields"]["members"][2] == {"classification": "oper", "count": "2",
                                          "labor_rate_id": 1, "hourly_rate_override": None,
                                          "sort_order": 1}


def test_a_typed_member_on_a_library_crew_below_its_banner(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.cw_row(ws, "MEMBER", 3), {
        CW.CODE: "Laborer", CW.COUNT: 1, CW.OVERRIDE: 45}), sheet=H.CW_TAB)
    (op,) = H.read(path).ops
    assert op["ref"] == 2 and op["v"] == "331a990f8c627d9c"
    assert [m["classification"] for m in op["fields"]["members"]] == ["Laborer", "Finisher"]


def test_a_member_with_an_unknown_classification_and_no_override_is_refused(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.cw_row(ws, "CREW_END", parent=1), {
        CW.CODE: "Welder", CW.COUNT: 1}), sheet=H.CW_TAB)
    assert any("matches no labour rate" in m for m in _refused(path))


def test_a_cleared_member_count_is_one_problem(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: ws.__setitem__(f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 1)}", None),
          sheet=H.CW_TAB)
    messages = _refused(path)
    assert len(messages) == 1 and "can't be cleared" in messages[0]


def test_a_copied_member_keeps_its_rate_link(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        r = H.cw_row(ws, "MEMBER", 2)
        H.insert_copies(ws, r, r, H.cw_row(ws, "CREW_END", parent=1))
    _edit(path, copy, sheet=H.CW_TAB)
    (op,) = H.read(path).ops
    assert op["fields"]["members"][2]["labor_rate_id"] == 1


def test_a_typed_row_outside_any_block_is_refused(tmp_path):
    path = _book(tmp_path)

    def typed(ws):
        r = H.cr_row(ws, "ACTIVITY", 2)    # between activity 1's END and activity 2
        H.type_row(ws, r, {"B": "Stray", "C": 1})
    _edit(path, typed)
    assert any("outside any block" in m for m in _refused(path))


def test_a_typed_row_under_an_unstepped_activity_is_refused(tmp_path):
    path = _book(tmp_path)

    def typed(ws):
        H.type_row(ws, H.cr_row(ws, "START", parent=1), {"B": "Set out", "C": 1})
    _edit(path, typed)
    assert any("add the activity's first step in BidSheet.ai" in m for m in _refused(path))


# -- deletes ---------------------------------------------------------------------

def test_a_deleted_resource(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: ws.delete_rows(H.cr_row(ws, "RESOURCE", 4)))
    cs = H.read(path)
    assert cs.ops == [{"op": "resource.delete", "ref": 4, "v": "99bc399cd92ef974",
                       "fields": {}}]
    assert cs.rows == [{"op_index": 0, "sheet": H.CR_TAB, "row": None}]


def test_a_parent_and_child_deleted_is_one_delete(tmp_path):
    path = _book(tmp_path)

    def delete(ws):
        first, last = _block(ws, 2, 3)
        ws.delete_rows(first, last - first + 1)
    _edit(path, delete)
    assert [(op["op"], op["ref"]) for op in H.read(path).ops] == [("activity.delete", 2)]


def test_a_deleted_step(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: ws.delete_rows(H.cr_row(ws, "STEP", 1)))
    assert [(op["op"], op["ref"]) for op in H.read(path).ops] == [("step.delete", 1)]


def test_a_deleted_member(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda ws: ws.delete_rows(H.cw_row(ws, "MEMBER", 1)), sheet=H.CW_TAB)
    (op,) = H.read(path).ops
    assert [m["classification"] for m in op["fields"]["members"]] == ["OPER"]


def test_a_child_left_behind_by_its_deleted_parent_becomes_a_root(tmp_path):
    path = _book(tmp_path)

    def delete(ws):
        first, last = _block(ws, 2)
        ws.delete_rows(first, last - first + 1)
    _edit(path, delete)
    cs = H.read(path)
    assert [(op["op"], op["ref"], op["fields"]) for op in cs.ops] == [
        ("activity.move", 3, {"parent_id": None}), ("activity.delete", 2, {})]


@pytest.mark.parametrize("kind, ident", [("ITEM", 2), ("ELEMENT_QTY", 1)])
def test_a_deleted_item_or_quantity_row_is_refused(tmp_path, kind, ident):
    path = _book(tmp_path)
    _edit(path, lambda ws: ws.delete_rows(H.cr_row(ws, kind, ident)))
    assert any("can't be deleted from the workbook" in m for m in _refused(path))


def test_a_copied_item_row_is_refused(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        r = H.cr_row(ws, "ITEM", 3)
        H.insert_copies(ws, r, r, r)
    _edit(path, copy)
    assert "rows of this kind can't be added or copied in the workbook" in _refused(path)


def test_an_allocation_posted_resource_deleted_is_refused(tmp_path):
    doc = H.fixture_doc()
    next(r for r in doc["resources"] if r["id"] == 8)["managed_by"] = "allocation"
    path = _book(tmp_path, doc)
    _edit(path, lambda ws: ws.delete_rows(H.cr_row(ws, "RESOURCE", 8)))
    assert any("posted by a subcontractor allocation" in m for m in _refused(path))


def test_an_allocation_posted_resource_cut_is_refused(tmp_path):
    doc = H.fixture_doc()
    next(r for r in doc["resources"] if r["id"] == 8)["managed_by"] = "allocation"
    path = _book(tmp_path, doc)

    def cut(ws):
        r = H.cr_row(ws, "RESOURCE", 8)
        H.cut_rows(ws, r, r, H.block_end(ws, 1))
    _edit(path, cut)
    assert any("posted by a subcontractor allocation" in m for m in _refused(path))


# -- cuts and moves --------------------------------------------------------------

def test_a_resource_cut_into_another_activity(tmp_path):
    path = _book(tmp_path)

    def cut(ws):
        r = H.cr_row(ws, "RESOURCE", 7)
        H.cut_rows(ws, r, r, H.block_end(ws, 1))
    _edit(path, cut)
    cs = H.read(path)
    assert cs.ops == [
        {"op": "resource.create", "ref": "new:r1", "fields": {
            "activity_id": 1, "name": "Concrete", "quantity": "1", "unit_cost": "1000.01",
            "component_type": "material", "labor_cost_basis": "production",
            "includes_burden": False}},
        {"op": "resource.delete", "ref": 7, "v": "bab71daf430b3e97", "fields": {}}]


def test_an_activity_block_cut_to_another_item_is_one_move(tmp_path):
    path = _book(tmp_path)

    def cut(ws):
        first, last = _block(ws, 2, 3)
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 7))
    _edit(path, cut)
    cs = H.read(path)
    assert cs.ops == [{"op": "activity.move", "ref": 2, "v": "b96859bc0ac1b1c5",
                       "fields": {"item_id": 4}}]


def test_a_move_comes_before_a_copy_created_under_the_moved_parent(tmp_path):
    path = _book(tmp_path)

    def cut_and_copy(ws):
        first, last = _block(ws, 2, 3)
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 7))
        child, child_end = _block(ws, 3)
        H.insert_copies(ws, child, child_end, child_end + 1)
    _edit(path, cut_and_copy)
    ops = H.read(path).ops
    assert [op["op"] for op in ops[:2]] == ["activity.move", "activity.create"]
    assert ops[1]["fields"]["parent_id"] == 2 and ops[1]["fields"]["estimate_item_id"] == 4


def test_a_move_of_an_activity_with_an_allocation_line_is_refused(tmp_path):
    doc = H.fixture_doc()
    next(r for r in doc["resources"] if r["id"] == 8)["managed_by"] = "allocation"
    path = _book(tmp_path, doc)

    def cut(ws):
        first, last = _block(ws, 7)
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 8))
    _edit(path, cut)
    assert any("subcontractor allocation work" in m for m in _refused(path))


def test_a_move_of_a_subcontractor_spread_is_refused(tmp_path):
    doc = H.fixture_doc()
    next(a for a in doc["activities"] if a["id"] == 7)["assembly_type"] = "SUBCONTRACTOR_SPREADS"
    path = _book(tmp_path, doc)

    def cut(ws):
        first, last = _block(ws, 7)
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 8))
    _edit(path, cut)
    assert any("subcontractor allocation work" in m for m in _refused(path))


def test_a_parent_copied_with_its_children(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        first, last = _block(ws, 2, 3)
        H.insert_copies(ws, first, last, H.cr_row(ws, "ACTIVITY", 4))
    _edit(path, copy)
    cs = H.read(path)
    creates = [(op["op"], op["ref"], op["fields"].get("parent_id"),
                op["fields"].get("activity_id")) for op in cs.ops]
    assert creates == [
        ("activity.create", "new:a1", None, None),
        ("activity.create", "new:a2", "new:a1", None),
        ("resource.create", "new:r1", None, "new:a1"),
        ("resource.create", "new:r2", None, "new:a1"),
        ("resource.create", "new:r3", None, "new:a2")]   # activities 2 and 3 have no crew
    assert cs.ops[0]["fields"] == {"estimate_item_id": 1, "name": "Walls",
                                   "assembly_type": "GENERIC", "production_rate": "1.5",
                                   "production_unit": "DAYS", "hours_per_shift": "8",
                                   "crew_factor": "1.1", "count": 2}
    assert any("not priced live" in n and "'Walls'" in n for n in cs.notes)


def test_a_copied_stepped_activity_adds_its_steps(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        first, last = _block(ws, 4)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    ops = H.read(path).ops
    assert [(op["op"], op["ref"]) for op in ops] == [
        ("activity.create", "new:a1"), ("step.add", "new:s1"),
        ("resource.create", "new:r1"), ("resource.create", "new:r2")]
    assert ops[1]["fields"]["activity_id"] == "new:a1"


def test_a_copied_unstepped_activity_carries_its_shifts(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        first, last = _block(ws, 1)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    ops = H.read(path).ops
    assert [(op["op"], op["ref"]) for op in ops] == [
        ("activity.create", "new:a1"), ("activity.update", "new:a1"),
        ("resource.create", "new:r1"), ("activity.set_crew", "new:a1")]
    assert ops[1]["fields"] == {"duration_shifts": "3"}


def test_a_copied_crew_priced_activity_keeps_its_crew_and_cost_code(tmp_path):
    doc = H.fixture_doc()
    next(a for a in doc["activities"] if a["id"] == 1)["activity_code"] = {"id": 11,
                                                                          "code": "2100"}
    path = _book(tmp_path, doc)

    def copy(ws):
        first, last = _block(ws, 1)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    cs = H.read(path)
    assert cs.ops[0]["op"] == "activity.create"
    assert cs.ops[0]["fields"]["activity_code_id"] == 11
    assert cs.ops[-1] == {"op": "activity.set_crew", "ref": "new:a1", "fields": {"crew_id": 1}}
    assert not any(op["op"] in ("activity.set_links", "activity.set_spread") for op in cs.ops)


def test_a_copy_without_a_crew_sets_none(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        first, last = _block(ws, 5)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    ops = H.read(path).ops
    assert "activity.set_crew" not in {op["op"] for op in ops}
    assert "activity_code_id" not in ops[0]["fields"]


def test_a_copy_sets_its_crew_after_the_crew_rosters(tmp_path):
    path = _book(tmp_path)
    wb = H.open_book(path)
    cr, cw = wb[H.CR_TAB], wb[H.CW_TAB]
    first, last = _block(cr, 6)                       # activity 6: library crew 2
    H.insert_copies(cr, first, last, last + 1)
    cw[f"{CW.COUNT}{H.cw_row(cw, 'MEMBER', 3)}"] = 4  # edits library crew 2's roster
    H.save_book(wb, path)
    ops = H.read(path).ops
    names = [op["op"] for op in ops]
    assert names.index("crew.update_members") < names.index("activity.set_crew")
    assert ops[names.index("activity.set_crew")] == {
        "op": "activity.set_crew", "ref": "new:a1", "fields": {"crew_id": 2}}


def test_a_copied_structure_activity_is_refused(tmp_path):
    doc = H.fixture_doc()
    next(a for a in doc["activities"] if a["id"] == 8)["assembly_type"] = "STRUCTURE"
    path = _book(tmp_path, doc)

    def copy(ws):
        first, last = _block(ws, 8)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    assert any("structure activities are added, deleted and moved in the takeoff" in m for m in _refused(path))


# -- review additions ------------------------------------------------------------

def test_a_typed_member_above_a_library_banner_is_a_new_member(tmp_path):
    """The NOTE banner sits inside the crew block: a row typed between the
    CREW row and the banner is that crew's new member."""
    path = _book(tmp_path)
    _edit(path, lambda ws: H.type_row(ws, H.cw_row(ws, "NOTE", parent=2), {
        CW.CODE: "Laborer", CW.COUNT: 1, CW.OVERRIDE: 45}), sheet=H.CW_TAB)
    (op,) = H.read(path).ops
    assert op["op"] == "crew.update_members" and op["ref"] == 2
    assert [m["classification"] for m in op["fields"]["members"]] == ["Laborer", "Finisher"]


def test_a_child_cut_away_from_a_counted_parent_names_the_lost_multiplier(tmp_path):
    path = _book(tmp_path)

    def cut(ws):
        first, last = _block(ws, 3)                       # Ties, under Walls (count 2)
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 7))
    _edit(path, cut)
    cs = H.read(path)
    assert [(op["op"], op["ref"], op["fields"]) for op in cs.ops] == [
        ("activity.move", 3, {"item_id": 4})]
    assert any("'Ties'" in n and "'Walls'" in n and "multiplied by 2" in n for n in cs.notes)


def test_a_child_left_behind_by_its_deleted_parent_names_the_lost_multiplier(tmp_path):
    path = _book(tmp_path)

    def delete(ws):
        first, last = _block(ws, 2)
        ws.delete_rows(first, last - first + 1)
    _edit(path, delete)
    assert any("'Ties'" in n and "multiplied by 2" in n for n in H.read(path).notes)


def test_a_child_moved_with_its_parent_keeps_its_multiplier(tmp_path):
    path = _book(tmp_path)

    def cut(ws):
        first, last = _block(ws, 2, 3)
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 7))
    _edit(path, cut)
    assert not any("multiplied" in n for n in H.read(path).notes)


def test_a_step_cut_into_another_stepped_activity(tmp_path):
    doc = H.fixture_doc()
    act5 = next(a for a in doc["activities"] if a["id"] == 5)
    act5["steps"] = [{"id": 2, "name": "Cure", "duration": "2", "duration_unit": "DAYS",
                      "sort_order": 0, "activity_code_id": None, "notes": "",
                      "v": "aaaaaaaaaaaaaaaa"}]
    path = _book(tmp_path, doc)

    def cut(ws):
        r = H.cr_row(ws, "STEP", 1)
        H.cut_rows(ws, r, r, H.cr_row(ws, "START", parent=5))
    _edit(path, cut)
    cs = H.read(path)
    assert [(op["op"], op["ref"]) for op in cs.ops] == [("step.add", "new:s1"),
                                                         ("step.delete", 1)]
    assert cs.ops[0]["fields"]["activity_id"] == 5
    assert any("moves here from activity 4" in line for line in cs.summary)


# -- review round 2 --------------------------------------------------------------

NO_ADD_TEXT = "rows of this kind can't be added or copied in the workbook"


def _walls_and_ties_copied_above_prep(ws):
    """Walls (count 2) and its child Ties copied, as one run, above Prep."""
    first, last = _block(ws, 2, 3)
    H.insert_copies(ws, first, last, H.cr_row(ws, "ACTIVITY", 4))


def _shape(ops):
    return [(op["op"], op["ref"], op["fields"].get("parent_id"),
             op["fields"].get("activity_id"), op["fields"].get("count")) for op in ops]


def test_a_parent_copied_with_its_child_then_the_original_parent_edited(tmp_path):
    """The copy gets its own copied child; the original never gains one."""
    path = _book(tmp_path)

    def edit(ws):
        _walls_and_ties_copied_above_prep(ws)
        ws[f"{CR.COUNT}{H.cr_row(ws, 'ACTIVITY', 2)}"] = 5    # the original Walls
    _edit(path, edit)
    # The unedited copy reads as the original (it equals the baseline); the
    # edited block is the new one, its Ties under its own Walls.
    assert _shape(H.read(path).ops) == [
        ("activity.create", "new:a1", None, None, 5),
        ("activity.create", "new:a2", "new:a1", None, 3),
        ("resource.create", "new:r1", None, "new:a1", None),
        ("resource.create", "new:r2", None, "new:a1", None),
        ("resource.create", "new:r3", None, "new:a2", None)]


def test_a_parent_copied_with_its_child_then_the_original_child_edited(tmp_path):
    path = _book(tmp_path)

    def edit(ws):
        _walls_and_ties_copied_above_prep(ws)
        ws[f"{CR.COUNT}{H.cr_row(ws, 'ACTIVITY', 3)}"] = 5    # the original Ties
    _edit(path, edit)
    assert _shape(H.read(path).ops) == [
        ("activity.create", "new:a1", None, None, 2),
        ("activity.create", "new:a2", "new:a1", None, 3),
        ("activity.update", 3, None, None, 5),
        ("resource.create", "new:r1", None, "new:a1", None),
        ("resource.create", "new:r2", None, "new:a1", None),
        ("resource.create", "new:r3", None, "new:a2", None)]


def test_an_original_child_left_under_a_copy_of_its_parent_is_refused(tmp_path):
    path = _book(tmp_path)

    def edit(ws):
        _walls_and_ties_copied_above_prep(ws)
        first, last = _block(ws, 3)                        # the original Ties
        ws.delete_rows(first, last - first + 1)
        copy = H.cr_row(ws, "ACTIVITY", 2, start=H.block_end(ws, 2) + 1)
        ws[f"{CR.COUNT}{copy}"] = 4
    _edit(path, edit)
    assert any("now sits under a copy of its parent" in m for m in _refused(path))


def test_an_item_row_pasted_from_another_book_is_refused_not_crashed(tmp_path):
    path = _book(tmp_path)

    def paste(ws):
        r = H.cr_row(ws, "ITEM", 4)
        new = H.insert_copies(ws, r, r, H.cr_row(ws, "ACTIVITY", 5))
        ws[f"{CR.ID}{new}"] = 99
    _edit(path, paste)
    assert NO_ADD_TEXT in _refused(path)


def _coded_doc(dest_code):
    """Step 1 (on Prep, code 11) carries sub-code 21; Pour gets a step of its
    own and cost code ``dest_code``."""
    doc = H.fixture_doc()
    acts = {a["id"]: a for a in doc["activities"]}
    acts[4]["activity_code"] = {"id": 11, "code": "2100"}
    acts[4]["steps"][0]["activity_code_id"] = 21
    acts[5]["activity_code"] = {"id": dest_code, "code": "x"} if dest_code else None
    acts[5]["steps"] = [{"id": 2, "name": "Cure", "duration": "2", "duration_unit": "DAYS",
                         "sort_order": 0, "activity_code_id": None, "notes": "",
                         "v": "aaaaaaaaaaaaaaaa"}]
    return doc


def _cut_step_1_to_pour(ws):
    r = H.cr_row(ws, "STEP", 1)
    H.cut_rows(ws, r, r, H.cr_row(ws, "START", parent=5))


def test_a_cut_step_keeps_its_code_under_the_same_activity_code(tmp_path):
    path = _book(tmp_path, _coded_doc(11))
    _edit(path, _cut_step_1_to_pour)
    cs = H.read(path)
    assert cs.ops[0]["op"] == "step.add" and cs.ops[0]["fields"]["activity_code_id"] == 21
    assert not any("cost code" in n for n in cs.notes)


@pytest.mark.parametrize("dest_code", [None, 12])
def test_a_cut_step_drops_a_code_the_new_activity_cannot_offer(tmp_path, dest_code):
    path = _book(tmp_path, _coded_doc(dest_code))
    _edit(path, _cut_step_1_to_pour)
    cs = H.read(path)
    assert cs.ops[0]["op"] == "step.add" and "activity_code_id" not in cs.ops[0]["fields"]
    assert any("'Set out'" in n and "cost code" in n for n in cs.notes)


def test_a_copied_stepped_activity_keeps_its_steps_codes(tmp_path):
    path = _book(tmp_path, _coded_doc(None))

    def copy(ws):
        first, last = _block(ws, 4)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    ops = H.read(path).ops
    assert ops[0]["fields"]["activity_code_id"] == 11
    assert ops[1]["op"] == "step.add" and ops[1]["fields"]["activity_code_id"] == 21


def _described(doc):
    res = next(r for r in doc["resources"] if r["id"] == 1)
    res.update({"description": "Long reach", "activity_code_id": 31, "trade": "Operators",
                "pieces": "2"})
    return doc


def test_a_linked_resource_cut_keeps_its_link_cost_and_unpriced_fields(tmp_path):
    path = _book(tmp_path, _described(H.linked_doc()))

    def cut(ws):
        r = H.cr_row(ws, "RESOURCE", 1)
        H.cut_rows(ws, r, r, H.block_end(ws, 5))
    _edit(path, cut)
    create, delete = H.read(path).ops
    assert create["op"] == "resource.create" and create["fields"]["activity_id"] == 5
    assert {k: create["fields"].get(k) for k in (
        "equipment_rate_id", "unit_cost", "description", "activity_code_id", "trade",
        "pieces")} == {"equipment_rate_id": 7, "unit_cost": "185", "description": "Long reach",
                       "activity_code_id": 31, "trade": "Operators", "pieces": "2"}
    assert (delete["op"], delete["ref"]) == ("resource.delete", 1)


def test_a_copied_resource_carries_its_unpriced_fields(tmp_path):
    path = _book(tmp_path, _described(H.fixture_doc()))

    def copy(ws):
        r = H.cr_row(ws, "RESOURCE", 1)
        H.insert_copies(ws, r, r, H.block_end(ws, 1))
    _edit(path, copy)
    (op,) = H.read(path).ops
    assert {k: op["fields"].get(k) for k in ("description", "activity_code_id", "trade",
                                             "pieces")} == {
        "description": "Long reach", "activity_code_id": 31, "trade": "Operators",
        "pieces": "2"}


def test_a_copied_activity_carries_its_description(tmp_path):
    doc = H.fixture_doc()
    next(a for a in doc["activities"] if a["id"] == 5)["description"] = "Deck pour"
    path = _book(tmp_path, doc)

    def copy(ws):
        first, last = _block(ws, 5)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    assert H.read(path).ops[0]["fields"]["description"] == "Deck pour"


def test_a_resource_cut_into_a_copied_activity_is_a_cut(tmp_path):
    path = _book(tmp_path, _described(H.fixture_doc()))

    def edit(ws):
        first, last = _block(ws, 5)                        # Pour, copied below itself
        H.insert_copies(ws, first, last, last + 1)
        r = H.cr_row(ws, "RESOURCE", 1)
        H.cut_rows(ws, r, r, H.cr_row(ws, "END", parent=5, start=last + 1))
    _edit(path, edit)
    cs = H.read(path)
    cut = next(op for op in cs.ops if op["op"] == "resource.create"
               and op["fields"]["name"] == "CAT 336")
    assert cut["fields"]["activity_id"] == "new:a1"
    assert cut["fields"]["description"] == "Long reach"
    assert ("resource.delete", 1) in [(op["op"], op["ref"]) for op in cs.ops]
    assert any("moves here from activity 1" in line for line in cs.summary)


def test_a_parent_cut_away_leaves_its_child_moved_back_by_item(tmp_path):
    path = _book(tmp_path)

    def cut(ws):
        first, last = _block(ws, 2)                        # Walls only; Ties stays
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 7))
    _edit(path, cut)
    assert [(op["op"], op["ref"], op["fields"]) for op in H.read(path).ops] == [
        ("activity.move", 2, {"item_id": 4}), ("activity.move", 3, {"item_id": 1})]


def test_a_structure_child_left_by_its_deleted_parent_is_refused(tmp_path):
    path = _book(tmp_path, _ties_structure())

    def delete(ws):
        first, last = _block(ws, 2)
        ws.delete_rows(first, last - first + 1)
    _edit(path, delete)
    messages = _refused(path)
    assert any("parent was deleted" in m for m in messages)
    assert not any("undo the move" in m for m in messages)


def test_every_added_resource_is_named_as_reaching_the_flat_sheet_after_rebuild(tmp_path):
    path = _book(tmp_path)

    def copy(ws):
        r = H.cr_row(ws, "RESOURCE", 1)
        H.insert_copies(ws, r, r, H.block_end(ws, 1))
    _edit(path, copy)
    assert any("'CAT 336'" in n and "Flat sheet" in n for n in H.read(path).notes)


def test_a_value_typed_between_bid_form_items_is_noted_and_ignored(tmp_path):
    path = _book(tmp_path)

    def typed(ws):
        r = H.find_row(ws, "ITEM_BID", 3, kind_col="J", id_col="K")
        H.type_row(ws, r, {"A": "Z9", "B": "New item", "D": 3})
    _edit(path, typed, sheet=H.BF_TAB)
    cs = H.read(path)
    assert cs.ops == []
    assert any("ignored" in n and "add bid items in BidSheet.ai" in n for n in cs.notes)


# -- untested plan rules ---------------------------------------------------------

def test_a_member_cut_into_another_crew(tmp_path):
    path = _book(tmp_path)

    def cut(ws):
        r = H.cw_row(ws, "MEMBER", 2)                       # OPER, crew 1
        H.cut_rows(ws, r, r, H.cw_row(ws, "CREW_END", parent=2))
    _edit(path, cut, sheet=H.CW_TAB)
    ops = H.read(path).ops
    assert [(op["ref"], [m["classification"] for m in op["fields"]["members"]])
            for op in ops] == [(1, ["Laborer"]), (2, ["Finisher", "OPER"])]
    assert ops[1]["fields"]["members"][1]["labor_rate_id"] == 1


def test_an_edited_allocation_posted_resource_is_refused(tmp_path):
    doc = H.fixture_doc()
    next(r for r in doc["resources"] if r["id"] == 8)["managed_by"] = "allocation"
    path = _book(tmp_path, doc)
    _edit(path, lambda ws: ws.__setitem__(f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 8)}", 7))
    assert any("posted by a subcontractor allocation" in m for m in _refused(path))


def test_an_ambiguous_classification_is_refused(tmp_path):
    doc = H.fixture_doc()
    doc["rates"]["labor"].append({"classification": "oper", "id": 2, "rate": "60.00",
                                  "unit": "HR"})
    path = _book(tmp_path, doc)
    _edit(path, lambda ws: H.type_row(ws, H.cw_row(ws, "CREW_END", parent=1), {
        CW.CODE: "Oper", CW.COUNT: 1}), sheet=H.CW_TAB)
    assert any("matches more than one labour rate" in m for m in _refused(path))


def _ties_structure():
    doc = H.fixture_doc()
    next(a for a in doc["activities"] if a["id"] == 3)["assembly_type"] = "STRUCTURE"
    return doc


def test_a_move_with_a_structure_row_in_its_subtree_is_refused(tmp_path):
    path = _book(tmp_path, _ties_structure())

    def cut(ws):
        first, last = _block(ws, 2, 3)
        H.cut_rows(ws, first, last, H.cr_row(ws, "ACTIVITY", 7))
    _edit(path, cut)
    assert any("structure activities are added, deleted and moved in the takeoff" in m for m in _refused(path))


def test_a_delete_with_a_structure_row_in_its_subtree_is_refused(tmp_path):
    path = _book(tmp_path, _ties_structure())

    def delete(ws):
        first, last = _block(ws, 2, 3)
        ws.delete_rows(first, last - first + 1)
    _edit(path, delete)
    assert any("was deleted" in m and "structure activities" in m for m in _refused(path))


# -- review round 3 --------------------------------------------------------------

def _pour_copied_below_itself(ws):
    first, last = _block(ws, 5)                            # Pour: element-linked
    H.insert_copies(ws, first, last, last + 1)
    return first, last + 1


def test_a_linked_activity_copied_with_one_copy_edited_is_refused(tmp_path):
    path = _book(tmp_path)

    def edit(ws):
        original, _copy = _pour_copied_below_itself(ws)
        ws[f"{CR.PROD}{original}"] = 9
    _edit(path, edit)
    messages = _refused(path)
    assert any("activity 'Pour' is linked to elements/spreads" in m
               and "can't tell which row keeps the links" in m for m in messages)


def test_a_linked_activity_copied_unedited_is_a_copy(tmp_path):
    path = _book(tmp_path)
    _edit(path, _pour_copied_below_itself)
    ops = H.read(path).ops
    assert [(op["op"], op["ref"]) for op in ops] == [("activity.create", "new:a1"),
                                                     ("resource.create", "new:r1")]


def test_an_unlinked_activity_copied_with_one_copy_edited_keeps_the_plan_rule(tmp_path):
    path = _book(tmp_path)

    def edit(ws):
        first, last = _block(ws, 1)                        # Excavate: no links
        H.insert_copies(ws, first, last, last + 1)
        ws[f"{CR.PROD}{first}"] = 9
    _edit(path, edit)
    ops = H.read(path).ops
    assert ops[0]["op"] == "activity.create" and ops[0]["fields"]["production_rate"] == "9"


def test_a_child_orphaned_above_its_parents_copy_becomes_a_root(tmp_path):
    """Walls and Ties copied above Prep, then the original Walls deleted: the
    original Ties now sits above any Walls, so it is not put under one."""
    path = _book(tmp_path)

    def edit(ws):
        _walls_and_ties_copied_above_prep(ws)
        first, last = _block(ws, 2)
        ws.delete_rows(first, last - first + 1)
    _edit(path, edit)
    cs = H.read(path)
    creates = [op for op in cs.ops if op["op"] == "activity.create"]
    assert [(op["fields"]["name"], op["fields"].get("parent_id")) for op in creates] == [
        ("Ties", None)]
    assert any("'Ties'" in n and "multiplied by 2" in n for n in cs.notes)


def test_a_parent_and_child_copy_inserted_between_them_is_a_copy(tmp_path):
    """Walls and Ties copied and inserted between Walls and Ties: the sheet
    reads Walls, Walls', Ties', Ties, so the upper Walls has no child and
    both Ties sit under Walls'. Every occurrence equals the baseline, so the
    original Walls is the one its child sits under (Walls'), and the read is
    what the book shows: a new childless Walls (the upper row) and a new Ties
    under Walls. (This was once refused, as a safe false positive, when the
    first Walls in sheet order was always taken as the original.)"""
    path = _book(tmp_path)

    def edit(ws):
        first, last = _block(ws, 2, 3)
        H.insert_copies(ws, first, last, H.cr_row(ws, "ACTIVITY", 3))
    _edit(path, edit)
    cs = H.read(path)
    creates = H.ops_named(cs, "activity.create")
    assert [(op["ref"], op["fields"]["name"], op["fields"].get("parent_id"))
            for op in creates] == [("new:a1", "Walls", None), ("new:a2", "Ties", 2)]
    assert not [op for op in cs.ops if op["op"] in ("activity.update", "activity.move")
                or op["op"].endswith(".delete")]
    wb = H.open_book(path)
    walls = H.cr_row(wb[H.CR_TAB], "ACTIVITY", 2)
    assert next(x["row"] for x in cs.rows if x["op_index"] == 0) == walls


def test_a_parent_copied_without_its_child_and_pasted_above_itself_is_a_copy(tmp_path):
    """Walls' own block (not Ties) inserted at Walls' row: the copy sits
    first, and Ties' positional parent is the lower Walls. Both Walls equal
    the baseline, so the original is the one Ties sits under, not the first
    in sheet order; the upper Walls is a new root with no children."""
    path = _book(tmp_path)

    def edit(ws):
        first, last = _block(ws, 2)
        H.insert_copies(ws, first, last, first)
    _edit(path, edit)
    cs = H.read(path)
    creates = H.ops_named(cs, "activity.create")
    assert [(op["ref"], op["fields"]["name"], op["fields"].get("parent_id"))
            for op in creates] == [("new:a1", "Walls", None)]
    assert [op["op"] for op in cs.ops] == ["activity.create", "resource.create",
                                           "resource.create"]
    assert all(op["fields"]["activity_id"] == "new:a1" for op in cs.ops[1:])
    wb = H.open_book(path)
    walls = H.cr_row(wb[H.CR_TAB], "ACTIVITY", 2)          # the upper (copied) Walls
    assert next(x["row"] for x in cs.rows if x["op_index"] == 0) == walls
