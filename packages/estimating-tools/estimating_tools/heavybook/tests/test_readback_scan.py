"""Markers and stray rows (spec §2 Scan, Markers)."""
from __future__ import annotations

import pytest

from estimating_tools.heavybook.tests import _readback as H
from estimating_tools.exchange.reader import ReadRefused, scan

MARKER = "a marker row was deleted or moved"


@pytest.fixture
def path(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")


def _edit(path, fn, sheet=H.CR_TAB):
    wb = H.open_book(path)
    fn(wb[sheet])
    H.save_book(wb, path)
    with pytest.raises(ReadRefused) as exc:
        H.read(path)
    return exc.value.problems


def test_an_unedited_book_scans_clean(path):
    assert H.read(path).ops == []


def test_a_deleted_start_marker_is_refused(path):
    problems = _edit(path, lambda ws: ws.delete_rows(H.cr_row(ws, "START", parent=2)))
    assert any(MARKER in p.message and "activity 2 (Walls)" in p.message for p in problems)


def test_a_duplicated_end_marker_is_refused(path):
    """The second END follows a block the first one closed: with a chain
    owner tag it has no open block to name, so it is a stray marker, at
    its own row."""
    def dup(ws):
        end = H.cr_row(ws, "END", parent=1)
        H.insert_copies(ws, end, end, end)
    problems = _edit(path, dup)
    end = H.cr_row(H.open_book(path)[H.CR_TAB], "END", parent=1)
    assert any(MARKER in p.message and "a stray END marker" in p.message and p.row == end + 1
               for p in problems)


def test_a_steps_marker_moved_into_another_activity_is_refused(path):
    """A marker's owner tag is a chain formula, so a moved STEPS marker
    names the activity it lands in: between that one's START and END it is
    out of place, and the activity it left has lost its marker."""
    def move(ws):
        steps = H.cr_row(ws, "STEPS", parent=4)
        H.cut_rows(ws, steps, steps, H.cr_row(ws, "END", parent=1))
    problems = _edit(path, move)
    assert any(MARKER in p.message and "activity 1 (Excavate)" in p.message for p in problems)
    assert any(MARKER in p.message and "activity 4 (Prep)" in p.message for p in problems)


def test_a_steps_marker_moved_into_an_activity_without_steps_is_refused(path):
    """In another activity's head zone the marker opens a steps block the
    baseline activity has none of (STEPS appears exactly when the activity
    has steps): refused at that activity's row, and at the one it left."""
    def move(ws):
        steps = H.cr_row(ws, "STEPS", parent=4)
        H.cut_rows(ws, steps, steps, H.cr_row(ws, "START", parent=1))
    problems = _edit(path, move)
    one = H.cr_row(H.open_book(path)[H.CR_TAB], "ACTIVITY", 1)
    assert any(MARKER in p.message and "activity 1 (Excavate)" in p.message and p.row == one
               for p in problems)
    assert any(MARKER in p.message and "activity 4 (Prep)" in p.message for p in problems)


def test_a_deleted_steps_marker_is_refused(path):
    problems = _edit(path, lambda ws: ws.delete_rows(H.cr_row(ws, "STEPS", parent=4)))
    assert any(MARKER in p.message and "activity 4 (Prep)" in p.message for p in problems)


def test_a_deleted_crew_end_is_refused(path):
    problems = _edit(path, lambda ws: ws.delete_rows(H.cw_row(ws, "CREW_END", parent=1)),
                     sheet=H.CW_TAB)
    assert any(MARKER in p.message and "crew 1 (Excavation crew)" in p.message
               for p in problems)


def test_an_unknown_kind_is_refused(path):
    def bad(ws):
        ws[f"W{H.cr_row(ws, 'RESOURCE', 1)}"] = "WIDGET"
    problems = _edit(path, bad)
    assert any("unknown row kind 'WIDGET'" in p.message for p in problems)


TYPED = "something was typed on a marker row"


def _cr_marker(kind, parent):
    return lambda ws: H.cr_row(ws, kind, parent=parent)


def _cw_marker(kind, parent):
    return lambda ws: H.cw_row(ws, kind, parent=parent)


@pytest.mark.parametrize("sheet, find, col, value", [
    (H.CR_TAB, _cr_marker("STEPS", 4), "M", 100),
    (H.CR_TAB, _cr_marker("START", 1), "C", 5),
    (H.CR_TAB, _cr_marker("END", 1), "C", 5),
    (H.CR_TAB, _cr_marker("END", 1), "B", "my note"),
    (H.CW_TAB, _cw_marker("CREW_END", 1), "C", 4),
    (H.CW_TAB, _cw_marker("NOTE", 2), "C", 4),
    (H.CW_TAB, _cw_marker("NOTE", 2), "B", "renamed banner"),
], ids=["steps", "start", "end", "end-cue", "crew-end", "note", "note-banner"])
def test_a_value_typed_on_a_marker_row_is_refused(path, sheet, find, col, value):
    def typed(ws):
        ws[f"{col}{find(ws)}"] = value
    problems = _edit(path, typed, sheet=sheet)
    assert any(TYPED in p.message and p.sheet == sheet for p in problems)


def test_norm_id_reads_only_ascii_digits_as_ints():
    assert scan.norm_id("7") == 7 and scan.norm_id(7.0) == 7
    assert scan.norm_id("²") == "²"


def test_a_marker_outside_any_block_is_named_a_stray_marker(path):
    """A marker's owner tag is a chain formula the reader does not read, so
    one pasted where no block is has no owner to name."""
    def paste(ws):
        end = H.cr_row(ws, "END", parent=1)
        H.insert_copies(ws, end, end, H.cr_row(ws, "ITEM", 1))
    problems = _edit(path, paste)
    assert any("a stray END marker: a marker row was deleted or moved" in p.message
               for p in problems)
    assert not any("None" in p.message for p in problems)


def test_a_duplicated_steps_marker_is_refused(path):
    def dup(ws):
        steps = H.cr_row(ws, "STEPS", parent=4)
        H.insert_copies(ws, steps, steps, steps + 1)
    problems = _edit(path, dup)
    assert any(MARKER in p.message and "activity 4 (Prep)" in p.message for p in problems)


def test_a_duplicated_crew_end_is_refused(path):
    def dup(ws):
        end = H.cw_row(ws, "CREW_END", parent=1)
        H.insert_copies(ws, end, end, end + 1)
    problems = _edit(path, dup, sheet=H.CW_TAB)
    end = H.cw_row(H.open_book(path)[H.CW_TAB], "CREW_END", parent=1)
    assert any(MARKER in p.message and "a stray CREW_END marker" in p.message
               and p.row == end + 1 for p in problems)


@pytest.mark.parametrize("activity, before", [(1, 2), (4, 5)], ids=["plain", "stepped"])
def test_a_copied_activity_block_scans_clean(path, activity, before):
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    first = H.cr_row(ws, "ACTIVITY", activity)
    H.insert_copies(ws, first, H.block_end(ws, activity), H.cr_row(ws, "ACTIVITY", before))
    H.save_book(wb, path)
    H.read(path)


def test_a_step_row_outside_its_block_is_refused(path):
    def move(ws):
        step = H.cr_row(ws, "STEP", 1)
        H.cut_rows(ws, step, step, H.cr_row(ws, "START", parent=1))
    problems = _edit(path, move)
    assert any("this step row sits outside an activity's block" in p.message
               for p in problems)


def test_a_resource_row_outside_its_block_is_refused(path):
    def move(ws):
        res = H.cr_row(ws, "RESOURCE", 1)
        H.cut_rows(ws, res, res, H.cr_row(ws, "ITEM", 4))
    problems = _edit(path, move)
    assert any("this resource row sits outside an activity's block" in p.message
               for p in problems)


def test_an_element_quantity_row_inside_a_block_is_refused(path):
    def move(ws):
        qty = H.cr_row(ws, "ELEMENT_QTY", 1)
        H.cut_rows(ws, qty, qty, H.block_end(ws, 1))
    problems = _edit(path, move)
    assert any("an element quantity row sits inside activity 1 (Excavate)'s block"
               in p.message for p in problems)
