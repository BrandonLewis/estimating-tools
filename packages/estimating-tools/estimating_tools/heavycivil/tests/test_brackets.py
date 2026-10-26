"""The book's growable blocks, edited the way Excel edits them.

Steps, resources and crew members each sit between marker rows, and every
formula over them sums the bracketed range, so a row inserted anywhere
inside counts (read-back spec section 1; section 5 "Brackets"). Resource
formulas find their activity by position (AJ), so a copied resource row
prices against the activity it lands in (section 5 "Activity by
position"). Inserts and deletes go through ``_fieldbook``'s Excel
simulators: openpyxl's own ``insert_rows``/``delete_rows`` never rewrite
formula text."""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.tests._fieldbook import (
    simulate_delete_row,
    simulate_insert_copied_row,
)
from estimating_tools.estimate_spec.tests._formula_eval import evaluate as _evaluate
from estimating_tools.heavycivil import build, style
from estimating_tools.heavycivil.columns import CR, CW


def evaluate(book, path):
    """Evaluate into ``path`` (made if missing), so before/after saves differ."""
    path.mkdir(parents=True, exist_ok=True)
    return _evaluate(book, path)


def _f(v):
    return 0.0 if v in (None, "") else float(v)


def _find(ws, kind_col, kind, id_col, value):
    """The first row whose kind cell is ``kind`` and whose ``id_col`` holds
    ``value``, scanning the sheet as it stands after the edits."""
    for r in range(1, ws.max_row + 1):
        if ws[f"{kind_col}{r}"].value == kind and ws[f"{id_col}{r}"].value == value:
            return r
    raise AssertionError(f"no {kind} row with {id_col}={value!r}")


def _cr(ws, kind, *, rid=None, parent=None):
    """A Cost Report row: by id (X), or a marker by its activity (Z)."""
    if parent is not None:
        return _find(ws, CR.KIND, kind, CR.PARENT, parent)
    return _find(ws, CR.KIND, kind, CR.ID, rid)


def _activity(doc, name):
    return next(a for a in doc["activities"] if a["name"] == name)


def _insert_typed_row(ws, at, values):
    """Excel's plain row insert at ``at`` with ``values`` typed into it: no
    formulas and no hidden cells -- what an estimator gets by inserting a
    blank row and typing."""
    simulate_insert_copied_row(ws, at, at)
    for c in range(1, ws.max_column + 1):
        ws.cell(at, c).value = None
    for col, value in values.items():
        ws[f"{col}{at}"] = value


# -- steps -----------------------------------------------------------------------

def _prep(doc, book):
    """Prep: one 2-DAYS step, 8 hours/shift (the fixture's stepped activity)."""
    prep = _activity(doc, "Prep")
    ws = book["Cost Report"]
    return ws, prep["id"], _cr(ws, "STEP", rid=prep["steps"][0]["id"])


def _shifts(ws, ev, activity_id):
    return _f(ev[f"Cost Report!{CR.SHIFTS}{_cr(ws, 'ACTIVITY', rid=activity_id)}"])


@pytest.mark.parametrize("where", ["top", "bottom"])
def test_a_step_inserted_at_either_end_of_the_block_counts(doc, book, tmp_path, where):
    ws, prep, step = _prep(doc, book)
    at = step if where == "top" else _cr(ws, "START", parent=prep)
    simulate_insert_copied_row(ws, at, step)
    ws[f"{CR.QTY}{at}"] = 4
    ws[f"{CR.UNIT}{at}"] = "HOURS"
    ev = evaluate(book, tmp_path)
    assert _shifts(ws, ev, prep) == pytest.approx(2.5)      # 2 days + 4 h / 8


def test_a_step_inserted_between_two_steps_counts(doc, book, tmp_path):
    ws, prep, step = _prep(doc, book)
    simulate_insert_copied_row(ws, step, step)              # a second 2-DAYS step on top
    simulate_insert_copied_row(ws, step + 1, step)          # and one between the two
    ws[f"{CR.QTY}{step + 1}"] = 1
    ws[f"{CR.UNIT}{step + 1}"] = None                       # a blank unit is DAYS
    ev = evaluate(book, tmp_path)
    assert _shifts(ws, ev, prep) == pytest.approx(5.0)


def test_a_typed_step_counts(doc, book, tmp_path):
    ws, prep, _ = _prep(doc, book)
    _insert_typed_row(ws, _cr(ws, "START", parent=prep),
                      {CR.DESC: "Cure", CR.QTY: 1.5, CR.UNIT: "days"})
    ev = evaluate(book, tmp_path)
    # SUMIF compares text the way Excel does: "days" is not "HOURS".
    assert _shifts(ws, ev, prep) == pytest.approx(3.5)


def test_a_deleted_step_leaves_no_ref_error(doc, book, tmp_path):
    ws, prep, step = _prep(doc, book)
    simulate_delete_row(ws, step)
    act = _cr(ws, "ACTIVITY", rid=prep)
    assert "#REF!" not in ws[f"{CR.SHIFTS}{act}"].value
    ev = evaluate(book, tmp_path)
    assert _shifts(ws, ev, prep) == 0


def test_a_typed_hours_step_counts_as_hours(doc, book, tmp_path):
    ws, prep, _ = _prep(doc, book)
    _insert_typed_row(ws, _cr(ws, "START", parent=prep),
                      {CR.DESC: "Cure", CR.QTY: 4, CR.UNIT: "hours"})
    ev = evaluate(book, tmp_path)
    assert _shifts(ws, ev, prep) == pytest.approx(2.5)      # SUMIF is case-insensitive


@pytest.mark.parametrize("hps, expected", [(None, 2.5), (0, 2.5), (10, 2.4)])
def test_hours_per_shift_divides_inserted_hours(doc, book, tmp_path, hps, expected):
    ws, prep, step = _prep(doc, book)
    at = _cr(ws, "START", parent=prep)
    simulate_insert_copied_row(ws, at, step)
    ws[f"{CR.QTY}{at}"] = 4
    ws[f"{CR.UNIT}{at}"] = "HOURS"
    ws[f"{CR.HPS}{_cr(ws, 'ACTIVITY', rid=prep)}"] = hps    # blank and 0 mean 8
    ev = evaluate(book, tmp_path)
    assert _shifts(ws, ev, prep) == pytest.approx(expected)


def test_a_row_between_activity_and_steps_is_outside_the_sum(doc, book, tmp_path):
    ws, prep, _ = _prep(doc, book)
    _insert_typed_row(ws, _cr(ws, "STEPS", parent=prep), {CR.QTY: 99, CR.UNIT: "DAYS"})
    ev = evaluate(book, tmp_path)
    assert _shifts(ws, ev, prep) == pytest.approx(2.0)


# -- crews -----------------------------------------------------------------------

def _crew_rows(book, crew_id):
    ws = book["Crews"]
    return (ws, _find(ws, CW.KIND, "CREW", CW.ID, crew_id),
            _find(ws, CW.KIND, "CREW_END", CW.CREW, crew_id))


def _crew_with_members(doc, scope):
    return next(c for c in doc["crews"] if c["scope"] == scope and c["members"])


@pytest.mark.parametrize("scope, where", [
    ("estimate", "under_crew"), ("estimate", "above_end"),
    ("library", "between_crew_and_note"), ("library", "under_note"),
    ("library", "above_end"),
])
def test_a_member_inserted_anywhere_in_a_crew_block_counts(doc, book, tmp_path, scope, where):
    crew = _crew_with_members(doc, scope)
    ws, head, end = _crew_rows(book, crew["id"])
    at = {"under_crew": head + 1, "between_crew_and_note": head + 1,
          "under_note": head + 2, "above_end": end}[where]
    source = end - 1                                        # the last member, pre-insert
    before = evaluate(book, tmp_path / "a")
    simulate_insert_copied_row(ws, at, source)
    after = evaluate(book, tmp_path / "b")
    copied = next(m for m in crew["members"] if m["id"] == ws[f"{CW.ID}{at}"].value)
    assert _f(after[f"Crews!{CW.HEADCOUNT}{head}"]) == pytest.approx(
        _f(before[f"Crews!{CW.HEADCOUNT}{head}"]) + float(copied["count"]))
    assert _f(after[f"Crews!{CW.RATE}{head}"]) == pytest.approx(
        _f(before[f"Crews!{CW.RATE}{head}"])
        + float(copied["count"]) * float(copied["effective_hourly_rate"]))


def test_a_deleted_member_leaves_no_ref_error(doc, book, tmp_path):
    crew = _crew_with_members(doc, "estimate")
    ws, head, end = _crew_rows(book, crew["id"])
    before = evaluate(book, tmp_path / "a")
    gone = next(m for m in crew["members"] if m["id"] == ws[f"{CW.ID}{end - 1}"].value)
    simulate_delete_row(ws, end - 1)
    for col in (CW.HEADCOUNT, CW.RATE):
        assert "#REF!" not in ws[f"{col}{head}"].value
    after = evaluate(book, tmp_path / "b")
    assert _f(after[f"Crews!{CW.HEADCOUNT}{head}"]) == pytest.approx(
        _f(before[f"Crews!{CW.HEADCOUNT}{head}"]) - float(gone["count"]))


def test_a_member_added_to_a_crew_with_none(doc, tmp_path):
    crew = next(c for c in doc["crews"] if c["scope"] == "estimate")
    crew["members"] = []
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    ws, head, end = _crew_rows(book, crew["id"])
    assert end == head + 1
    _insert_typed_row(ws, end, {CW.CODE: "Laborer", CW.COUNT: 2})
    ev = evaluate(book, tmp_path / "typed")
    # A typed member's headcount counts live; its rate has no formulas yet.
    assert _f(ev[f"Crews!{CW.HEADCOUNT}{head}"]) == pytest.approx(2)
    assert _f(ev[f"Crews!{CW.RATE}{head}"]) == 0
    member = next(c for c in doc["crews"] if c["scope"] == "library")["members"][0]
    simulate_insert_copied_row(ws, head + 1, _find(ws, CW.KIND, "MEMBER", CW.ID, member["id"]))
    ev = evaluate(book, tmp_path / "copied")
    assert _f(ev[f"Crews!{CW.HEADCOUNT}{head}"]) == pytest.approx(2 + float(member["count"]))
    assert _f(ev[f"Crews!{CW.RATE}{head}"]) == pytest.approx(
        float(member["count"]) * float(member["effective_hourly_rate"]))


# -- activity by position --------------------------------------------------------

def _carpenters(doc):
    """Carpenters, on Walls: 2 x 400 x production 1.5 x crew factor 1.1 x
    burden 1.1 = 1452."""
    return next(r for r in doc["resources"] if r["name"] == "Carpenters")


def test_a_resource_copied_within_its_activity_prices_against_it(doc, book, tmp_path):
    ws = book["Cost Report"]
    walls, res = _activity(doc, "Walls")["id"], _carpenters(doc)
    end = _cr(ws, "END", parent=walls)
    before = evaluate(book, tmp_path / "a")
    simulate_insert_copied_row(ws, end, _cr(ws, "RESOURCE", rid=res["id"]))
    after = evaluate(book, tmp_path / "b")
    act = _cr(ws, "ACTIVITY", rid=walls)
    assert after[f"Cost Report!{CR.ACT}{end}"] == act
    assert _f(after[f"Cost Report!{CR.H2}{end}"]) == pytest.approx(1452)
    # Walls (count 2) now carries the line twice.
    assert _f(after[f"Cost Report!{CR.LAB}{act}"]) == pytest.approx(
        _f(before[f"Cost Report!{CR.LAB}{act}"]) + 2 * 1452)


def test_a_resource_copied_into_another_activity_prices_against_that_one(doc, book, tmp_path):
    """In Prep (no production rate) the copied line has no units, so it
    prices flat: 2 x 400 x burden 1.1 = 880."""
    ws = book["Cost Report"]
    prep = _activity(doc, "Prep")["id"]
    end = _cr(ws, "END", parent=prep)
    before = evaluate(book, tmp_path / "a")
    simulate_insert_copied_row(ws, end, _cr(ws, "RESOURCE", rid=_carpenters(doc)["id"]))
    after = evaluate(book, tmp_path / "b")
    act = _cr(ws, "ACTIVITY", rid=prep)
    assert after[f"Cost Report!{CR.ACT}{end}"] == act
    assert _f(after[f"Cost Report!{CR.H2}{end}"]) == pytest.approx(880)
    assert _f(after[f"Cost Report!{CR.LAB}{act}"]) == pytest.approx(
        _f(before[f"Cost Report!{CR.LAB}{act}"]) + 880)


def test_the_activity_row_chain_holds_across_a_typed_and_a_copied_row(doc, book, tmp_path):
    ws = book["Cost Report"]
    walls, prep = _activity(doc, "Walls")["id"], _activity(doc, "Prep")["id"]
    res = _carpenters(doc)
    # A typed line right under Walls' START: no AJ of its own ...
    typed = _cr(ws, "START", parent=walls) + 1
    _insert_typed_row(ws, typed, {CR.DESC: "Laborer", CR.QTY: 1, CR.UCOST: 300,
                                  CR.TYPE: "labor"})
    # ... and a copied line at the bottom of Prep.
    end = _cr(ws, "END", parent=prep)
    simulate_insert_copied_row(ws, end, _cr(ws, "RESOURCE", rid=res["id"]))
    ev = evaluate(book, tmp_path)
    walls_row, prep_row = _cr(ws, "ACTIVITY", rid=walls), _cr(ws, "ACTIVITY", rid=prep)
    assert ws[f"{CR.ACT}{typed}"].value is None
    # The row below the typed one still reads the row above the insert.
    original = _cr(ws, "RESOURCE", rid=res["id"])
    assert original == typed + 1
    assert ev[f"Cost Report!{CR.ACT}{original}"] == walls_row
    assert _f(ev[f"Cost Report!{CR.H2}{original}"]) == pytest.approx(1452)
    for r in range(prep_row, end + 1):
        assert ev[f"Cost Report!{CR.ACT}{r}"] == prep_row, r
    # The typed line is not priced live (it has no formulas) and adds
    # nothing to Walls until the apply and rebuild.
    assert ev[f"Cost Report!{CR.H2}{typed}"] in (None, "")


# -- deletes must not poison the AJ chain ----------------------------------------

def _errors(ev, ws_name, cols, last):
    return [f"{ws_name}!{c}{r}" for c in cols for r in range(1, last + 1)
            if str(ev[f"{ws_name}!{c}{r}"]).startswith("#")]


def _assert_no_errors(book, ev):
    cr, bf = book["Cost Report"], book["Bid Form"]
    assert _errors(ev, "Cost Report", (CR.TOTAL, CR.H2, CR.ACT), cr.max_row) == []
    assert _errors(ev, "Bid Form", ("A", "B", "H", "I"), bf.max_row) == []


def test_a_deleted_step_leaves_the_book_error_free(doc, book, tmp_path):
    ws, prep, step = _prep(doc, book)
    flat = _cr(ws, "RESOURCE", rid=next(r for r in doc["resources"]
                                         if r["name"] == "Flat crew")["id"])
    before = evaluate(book, tmp_path / "a")
    flat_cost = _f(before[f"Cost Report!{CR.H2}{flat}"])
    simulate_delete_row(ws, step)
    after = evaluate(book, tmp_path / "b")
    _assert_no_errors(book, after)
    flat = _cr(ws, "RESOURCE", rid=next(r for r in doc["resources"]
                                         if r["name"] == "Flat crew")["id"])
    assert _f(after[f"Cost Report!{CR.H2}{flat}"]) == pytest.approx(flat_cost)


def test_a_deleted_first_resource_leaves_the_book_error_free(doc, book, tmp_path):
    ws = book["Cost Report"]
    carp = _carpenters(doc)
    foreman = next(r for r in doc["resources"] if r["name"] == "Foreman")
    before = evaluate(book, tmp_path / "a")
    cost = _f(before[f"Cost Report!{CR.H2}{_cr(ws, 'RESOURCE', rid=foreman['id'])}"])
    simulate_delete_row(ws, _cr(ws, "RESOURCE", rid=carp["id"]))
    after = evaluate(book, tmp_path / "b")
    _assert_no_errors(book, after)
    row = _cr(ws, "RESOURCE", rid=foreman["id"])
    assert _f(after[f"Cost Report!{CR.H2}{row}"]) == pytest.approx(cost)
    assert after[f"Cost Report!{CR.ACT}{row}"] == _cr(ws, "ACTIVITY",
                                                       rid=_activity(doc, "Walls")["id"])


def test_a_deleted_first_data_row_leaves_the_activity_chain_intact(doc, book, tmp_path):
    ws = book["Cost Report"]
    simulate_delete_row(ws, 5)                              # the first ITEM
    ev = evaluate(book, tmp_path)
    assert _errors(ev, "Cost Report", (CR.ACT,), ws.max_row) == []
    for res in doc["resources"]:
        row = _cr(ws, "RESOURCE", rid=res["id"])
        act = _cr(ws, "ACTIVITY", rid=res["activity_id"])
        assert ev[f"Cost Report!{CR.ACT}{row}"] == act
        assert not str(ev[f"Cost Report!{CR.H2}{row}"]).startswith("#")


def test_a_copy_inserted_at_the_first_data_row_is_not_circular(doc, book, tmp_path):
    ws = book["Cost Report"]
    simulate_insert_copied_row(ws, 5, 5)
    ev = evaluate(book, tmp_path)
    assert _errors(ev, "Cost Report", (CR.ACT,), ws.max_row) == []
