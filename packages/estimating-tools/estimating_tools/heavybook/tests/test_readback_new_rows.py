"""New rows recognised by structure (#1486 sub-project 4): a kind-tagged row
with a blank id is new, and its position decides its parent. Inserted the
way Estimate Navigator does it (``H.insert_template``)."""
from __future__ import annotations

import pytest

from estimating_tools.heavybook.columns import CR, CW
from estimating_tools.exchange.reader import ReadRefused
from estimating_tools.exchange.reader.classify import FIRST_STEP
from estimating_tools.exchange.reader.ops import NO_STEPS_NEW
from estimating_tools.exchange.reader.scan import FIRST_STEP_NEW, MARKER
from estimating_tools.heavybook.tests import _readback as H


@pytest.fixture
def path(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")


def _edit(path, fn):
    """``fn(wb)`` on the saved book, then save it."""
    wb = H.open_book(path)
    fn(wb)
    H.save_book(wb, path)


def _refused(path):
    with pytest.raises(ReadRefused) as exc:
        H.read(path)
    return [p.message for p in exc.value.problems]


def _fill(ws, r, values):
    for letter, value in values.items():
        ws[f"{letter}{r}"] = value


def _insert_activity(wb, name, at, values=None):
    """The ``name`` prototype inserted above Cost Report row ``at``; ``values``
    maps a kind (or ``(kind, n)`` for the n-th row of that kind) to cells."""
    ws = wb[H.CR_TAB]
    first, last = H.template_rows(wb, name)
    H.insert_template(wb, name, H.CR_TAB, at)
    rows = list(range(at, at + last - first + 1))
    for key, cells in (values or {}).items():
        kind, n = key if isinstance(key, tuple) else (key, 0)
        _fill(ws, [r for r in rows if ws[f"{CR.KIND}{r}"].value == kind][n], cells)
    return rows


PUMP = {CR.DESC: "Pump", CR.QTY: 2, CR.UCOST: 80, CR.TYPE: "equipment"}


# -- resources -------------------------------------------------------------------

def test_a_new_resource_line_in_an_existing_activity(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        r = H.insert_template(wb, "hc.tpl.resource", H.CR_TAB, H.block_end(ws, 2))
        _fill(ws, r, PUMP)
    _edit(path, insert)
    cs = H.read(path)
    assert cs.ops == [{"op": "resource.create", "ref": "new:r1", "fields": {
        "activity_id": 2, "name": "Pump", "quantity": "2", "unit_cost": "80",
        "component_type": "equipment", "sort_order": 0}}]
    assert cs.summary == ["Cost Report row 15: new line 'Pump'"]
    assert not any("not priced live" in n for n in cs.notes)
    assert not any("pasted" in line for line in cs.summary + cs.notes)


def test_an_untouched_inserted_resource_is_skipped_with_a_note(path):
    _edit(path, lambda wb: H.insert_template(wb, "hc.tpl.resource", H.CR_TAB,
                                             H.block_end(wb[H.CR_TAB], 5)))
    cs = H.read(path)
    assert cs.ops == []
    assert cs.notes == ["Cost Report row 30: an empty inserted resource line was skipped"]


def test_a_new_resource_line_needs_a_type(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        r = H.insert_template(wb, "hc.tpl.resource", H.CR_TAB, H.block_end(ws, 2))
        _fill(ws, r, {CR.DESC: "Pump", CR.QTY: 2})
    _edit(path, insert)
    assert "a new resource line needs a Type" in _refused(path)


# -- steps -----------------------------------------------------------------------

def test_a_new_step_in_a_stepped_activity(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        r = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, H.cr_row(ws, "START", parent=4))
        _fill(ws, r, {CR.DESC: "Strip", CR.QTY: 4, CR.UNIT: "HOURS"})
    _edit(path, insert)
    cs = H.read(path)
    assert cs.ops == [{"op": "step.add", "ref": "new:s1", "fields": {
        "activity_id": 4, "name": "Strip", "duration": "4", "duration_unit": "HOURS"}}]
    assert cs.summary == ["Cost Report row 23: new step 'Strip'"]


def test_a_new_step_needs_a_duration(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        r = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, H.cr_row(ws, "START", parent=4))
        _fill(ws, r, {CR.DESC: "Strip"})
    _edit(path, insert)
    assert "a new step needs a duration" in _refused(path)


@pytest.mark.parametrize("marker", ["START", "END"])
def test_a_blank_id_step_in_an_activity_without_steps_is_refused(path, marker):
    def insert(wb):
        ws = wb[H.CR_TAB]
        r = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, H.cr_row(ws, marker, parent=1))
        _fill(ws, r, {CR.DESC: "Strip", CR.QTY: 1})
    _edit(path, insert)
    assert FIRST_STEP in _refused(path)


def test_an_untouched_inserted_step_is_skipped(path):
    _edit(path, lambda wb: H.insert_template(wb, "hc.tpl.step", H.CR_TAB,
                                             H.cr_row(wb[H.CR_TAB], "START", parent=4)))
    cs = H.read(path)
    assert cs.ops == [] and cs.notes == [
        "Cost Report row 23: an empty inserted step was skipped"]


# -- members ---------------------------------------------------------------------

def test_a_new_member_joins_the_crews_roster(path):
    def insert(wb):
        ws = wb[H.CW_TAB]
        r = H.insert_template(wb, "hc.tpl.member", H.CW_TAB, H.cw_row(ws, "CREW_END", parent=1))
        _fill(ws, r, {CW.CODE: "OPER", CW.COUNT: 2})
    _edit(path, insert)
    cs = H.read(path)
    (op,) = cs.ops
    assert op["op"] == "crew.update_members" and op["ref"] == 1
    assert op["fields"]["members"][2] == {"classification": "OPER", "count": "2",
                                          "labor_rate_id": 1, "hourly_rate_override": None,
                                          "sort_order": 1}
    assert any("the new member's library rate" in n for n in cs.notes)


def test_a_new_member_with_a_rate_override_prices_live(path):
    def insert(wb):
        ws = wb[H.CW_TAB]
        r = H.insert_template(wb, "hc.tpl.member", H.CW_TAB, H.cw_row(ws, "CREW_END", parent=1))
        _fill(ws, r, {CW.CODE: "Welder", CW.COUNT: 1, CW.OVERRIDE: 60})
    _edit(path, insert)
    cs = H.read(path)
    assert cs.ops[0]["fields"]["members"][2]["hourly_rate_override"] == "60"
    assert not any("not priced live" in n for n in cs.notes)


def test_a_new_member_needs_a_classification_and_a_count(path):
    def insert(wb):
        ws = wb[H.CW_TAB]
        r = H.insert_template(wb, "hc.tpl.member", H.CW_TAB, H.cw_row(ws, "CREW_END", parent=1))
        _fill(ws, r, {CW.CODE: "OPER"})
    _edit(path, insert)
    assert "a crew member needs a classification and a count" in _refused(path)


def test_an_untouched_inserted_member_is_skipped(path):
    _edit(path, lambda wb: H.insert_template(wb, "hc.tpl.member", H.CW_TAB,
                                             H.cw_row(wb[H.CW_TAB], "CREW_END", parent=1)))
    cs = H.read(path)
    assert cs.ops == [] and cs.notes == ["Crews row 8: an empty inserted crew member was skipped"]


# -- activities ------------------------------------------------------------------

def test_a_new_activity_between_two_existing_ones(path):
    """After Walls' tree (Walls, then its child Ties) and before Prep: a root
    of item 1 sorting with Walls (sort order 2), ahead of Prep (3)."""
    def insert(wb):
        _insert_activity(wb, "hc.tpl.activity", H.cr_row(wb[H.CR_TAB], "ACTIVITY", 4), {
            "ACTIVITY": {CR.DESC: "Dewater", CR.SHIFTS: 3, CR.COUNT: 2}, "RESOURCE": PUMP})
    _edit(path, insert)
    cs = H.read(path)
    assert cs.ops == [
        {"op": "activity.create", "ref": "new:a1", "fields": {
            "estimate_item_id": 1, "name": "Dewater", "assembly_type": "GENERIC",
            "sort_order": 2, "count": 2}},
        {"op": "activity.update", "ref": "new:a1", "fields": {"duration_shifts": "3"}},
        {"op": "resource.create", "ref": "new:r1", "fields": {
            "activity_id": "new:a1", "name": "Pump", "quantity": "2", "unit_cost": "80",
            "component_type": "equipment", "sort_order": 0}},
    ]
    assert "Cost Report row 20: new activity 'Dewater'" in cs.summary
    assert any("the new activity 'Dewater' in its item's total" in n for n in cs.notes)


def test_a_new_activity_as_its_items_first_sorts_before_the_first_root(path):
    def insert(wb):
        _insert_activity(wb, "hc.tpl.activity", H.cr_row(wb[H.CR_TAB], "ACTIVITY", 6), {
            "ACTIVITY": {CR.DESC: "Prime"}})
    _edit(path, insert)
    (op,) = H.read(path).ops
    assert op["fields"] == {"estimate_item_id": 2, "name": "Prime",
                            "assembly_type": "GENERIC", "sort_order": 0}


def test_a_new_stepped_activity_adds_its_steps(path):
    def insert(wb):
        _insert_activity(wb, "hc.tpl.stepped", H.cr_row(wb[H.CR_TAB], "ITEM", 2), {
            "ACTIVITY": {CR.DESC: "Seal"},
            "STEP": {CR.DESC: "Mask", CR.QTY: 2, CR.UNIT: "DAYS"}})
    _edit(path, insert)
    cs = H.read(path)
    assert [(op["op"], op["ref"]) for op in cs.ops] == [("activity.create", "new:a1"),
                                                       ("step.add", "new:s1")]
    assert cs.ops[1]["fields"]["activity_id"] == "new:a1"
    assert "Cost Report row 40: an empty inserted resource line was skipped" in cs.notes


def test_a_new_stepped_activity_with_no_step_filled_is_refused(path):
    """Created without steps, the fresh baseline would say ``steps=[]`` under
    a block that keeps its STEPS marker, and the next read would refuse it."""
    def insert(wb):
        _insert_activity(wb, "hc.tpl.stepped", H.cr_row(wb[H.CR_TAB], "ITEM", 2), {
            "ACTIVITY": {CR.DESC: "Seal"}, "RESOURCE": PUMP})
    _edit(path, insert)
    problems = _refused(path)
    assert problems == [NO_STEPS_NEW]


def test_an_untouched_inserted_block_is_skipped_as_one(path):
    _edit(path, lambda wb: _insert_activity(wb, "hc.tpl.stepped",
                                            H.cr_row(wb[H.CR_TAB], "ITEM", 2)))
    cs = H.read(path)
    assert cs.ops == []
    assert cs.notes == ["Cost Report row 36: an empty inserted activity was skipped"]


def test_a_partly_filled_block_needs_a_name(path):
    def insert(wb):
        _insert_activity(wb, "hc.tpl.activity", H.cr_row(wb[H.CR_TAB], "ITEM", 2), {
            "RESOURCE": PUMP})
    _edit(path, insert)
    assert "a new activity needs a name" in _refused(path)


def test_a_new_blocks_marker_moved_into_another_activity_is_refused(path):
    """A marker's owner tag is a chain formula, so a new block's START cut
    into Pour's block names Pour, where a second START has no place; the
    new block, left without one, is refused too."""
    def insert(wb):
        ws = wb[H.CR_TAB]
        rows = _insert_activity(wb, "hc.tpl.activity", H.cr_row(ws, "ITEM", 2), {
            "ACTIVITY": {CR.DESC: "Seal"}})
        H.cut_rows(ws, rows[1], rows[1], H.block_end(ws, 5))      # its START, into Pour
    _edit(path, insert)
    messages = _refused(path)
    assert any(MARKER in m and "activity 5 (Pour)" in m for m in messages)
    assert any(MARKER in m and "a new activity" in m for m in messages)


def test_a_new_activity_outside_any_item_is_refused(path):
    def insert(wb):
        _insert_activity(wb, "hc.tpl.activity", H.cr_row(wb[H.CR_TAB], "ITEM", 1), {
            "ACTIVITY": {CR.DESC: "Seal"}})
    _edit(path, insert)
    assert any("a new activity sits outside any item" in m for m in _refused(path))


# -- unchanged rules ---------------------------------------------------------------

def test_a_hand_typed_kind_marker_without_formulas_is_refused(path):
    def typed(wb):
        ws = wb[H.CR_TAB]
        H.type_row(ws, H.block_end(ws, 2), {CR.KIND: "RESOURCE", **PUMP})
    _edit(path, typed)
    assert any("held a formula and was cleared" in m for m in _refused(path))


# -- review fixes ------------------------------------------------------------------

def test_a_new_activity_after_a_root_moved_into_the_item_takes_its_sort_order(path):
    """Ties (Walls' child, sort 1) cut to item 2 above Finish ends up a root
    of item 2: a new activity inserted right after it takes Ties' sort
    order. Ties sort by id, so once applied it may land after other roots
    sharing that order (Finish here), as the spec documents."""
    def edit(wb):
        ws = wb[H.CR_TAB]
        first = H.cr_row(ws, "ACTIVITY", 3)
        H.cut_rows(ws, first, H.block_end(ws, 3), H.cr_row(ws, "ACTIVITY", 6))
        _insert_activity(wb, "hc.tpl.activity", H.cr_row(ws, "ACTIVITY", 6), {
            "ACTIVITY": {CR.DESC: "Prime"}})
    _edit(path, edit)
    (create,) = H.ops_named(H.read(path), "activity.create")
    assert create["fields"]["estimate_item_id"] == 2
    assert create["fields"]["sort_order"] == 1


def test_an_untouched_step_where_no_step_can_go_is_skipped(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        return H.insert_template(wb, "hc.tpl.step", H.CR_TAB, H.cr_row(ws, "START", parent=1))
    wb = H.open_book(path)
    r = insert(wb)
    H.save_book(wb, path)
    cs = H.read(path)
    assert cs.ops == [] and cs.notes == [f"Cost Report row {r}: an empty inserted step was skipped"]


def test_an_untouched_member_between_crews_is_skipped(path):
    wb = H.open_book(path)
    r = H.insert_template(wb, "hc.tpl.member", H.CW_TAB, H.cw_row(wb[H.CW_TAB], "CREW", 2))
    H.save_book(wb, path)
    cs = H.read(path)
    assert cs.ops == [] and cs.notes == [
        f"Crews row {r}: an empty inserted crew member was skipped"]


def test_a_filled_member_between_crews_is_still_refused(path):
    def insert(wb):
        ws = wb[H.CW_TAB]
        r = H.insert_template(wb, "hc.tpl.member", H.CW_TAB, H.cw_row(ws, "CREW", 2))
        _fill(ws, r, {CW.CODE: "OPER", CW.COUNT: 2})
    _edit(path, insert)
    assert any("this crew member row sits outside a crew's block" in m for m in _refused(path))


def test_a_filled_step_in_a_new_plain_activity_points_at_the_stepped_prototype(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        rows = _insert_activity(wb, "hc.tpl.activity", H.cr_row(ws, "ITEM", 2), {
            "ACTIVITY": {CR.DESC: "Seal"}})
        r = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, rows[1])     # above its START
        _fill(ws, r, {CR.DESC: "Mask", CR.QTY: 1})
    _edit(path, insert)
    problems = _refused(path)
    assert FIRST_STEP_NEW in problems and FIRST_STEP not in problems


def test_an_orphaned_marker_of_a_new_block_says_so(path):
    """Without its ACTIVITY row the block's START follows the activity
    above, whose block is closed: its owner tag (a chain formula) has no
    open block to name, so it is a stray marker."""
    def insert(wb):
        ws = wb[H.CR_TAB]
        rows = _insert_activity(wb, "hc.tpl.activity", H.cr_row(ws, "ITEM", 2))
        ws.delete_rows(rows[0])                       # the new ACTIVITY row
    _edit(path, insert)
    assert f"a stray START marker: {MARKER}" in _refused(path)


def test_a_value_in_a_non_input_column_makes_a_new_row_touched(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        r = H.insert_template(wb, "hc.tpl.resource", H.CR_TAB, H.block_end(ws, 2))
        _fill(ws, r, {CR.CODE: "X1"})
    _edit(path, insert)
    assert "a new resource line needs a name and a Type" in _refused(path)


# -- final review fixes --------------------------------------------------------------

OUTSIDE_STEP = ("this step row sits outside an activity's block (between its STEPS and START "
                "markers) -- move it back")


def test_a_filled_step_above_a_new_stepped_blocks_steps_marker_is_misplaced(path):
    """Between a new stepped block's ACTIVITY and STEPS rows: the activity is
    stepped, so the step is misplaced -- not a first step."""
    def insert(wb):
        ws = wb[H.CR_TAB]
        rows = _insert_activity(wb, "hc.tpl.stepped", H.cr_row(ws, "ITEM", 2), {
            "ACTIVITY": {CR.DESC: "Seal"}})
        r = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, rows[1])     # above its STEPS
        _fill(ws, r, {CR.DESC: "Mask", CR.QTY: 1})
    _edit(path, insert)
    problems = _refused(path)
    assert OUTSIDE_STEP in problems and FIRST_STEP_NEW not in problems


def test_a_filled_step_above_an_existing_steps_marker_is_misplaced(path):
    def insert(wb):
        ws = wb[H.CR_TAB]
        r = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, H.cr_row(ws, "STEPS", parent=4))
        _fill(ws, r, {CR.DESC: "Strip", CR.QTY: 1})
    _edit(path, insert)
    problems = _refused(path)
    assert OUTSIDE_STEP in problems and FIRST_STEP not in problems


def test_an_untouched_step_above_a_steps_marker_is_skipped(path):
    wb = H.open_book(path)
    r = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, H.cr_row(wb[H.CR_TAB], "STEPS", parent=4))
    H.save_book(wb, path)
    cs = H.read(path)
    assert cs.ops == [] and cs.notes == [f"Cost Report row {r}: an empty inserted step was skipped"]


def test_a_skipped_block_swallows_the_skips_inside_it(path):
    """A wholly blank block is skipped as one, even with an untouched step
    inserted in it (skipped on its own by scan)."""
    wb = H.open_book(path)
    rows = _insert_activity(wb, "hc.tpl.activity", H.cr_row(wb[H.CR_TAB], "ITEM", 2))
    H.insert_template(wb, "hc.tpl.step", H.CR_TAB, rows[1])               # above its START
    H.save_book(wb, path)
    cs = H.read(path)
    assert cs.ops == [] and cs.notes == [
        f"Cost Report row {rows[0]}: an empty inserted activity was skipped"]
