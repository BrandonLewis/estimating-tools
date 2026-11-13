"""#439: a declaration that leaves a kind out on purpose. A blocks sheet may
name in ``not_shown`` a kind its owner or container holds (an activity's
steps or resource lines, an item's element quantities): the loader accepts
the omission only when it is said, and the reader, the refresh and the
fill then never read, diff, insert or lay out a row of that kind. The test
pack is ``_template``'s mini-book with the kind taken out."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.reader import ReadRefused, read_book
from estimating_tools.exchange.reader.classify import STRAY
from estimating_tools.exchange.reader.ops import HIDDEN_STEPS
from estimating_tools.exchange.template import TemplatePack
from estimating_tools.exchange.tests import _template as T
from estimating_tools.heavybook.tests import _readback as H

AT = "2026-11-07T09:00:00Z"


def _without_steps(doc):
    est = doc["sheets"]["estimate"]
    est["not_shown"] = ["STEP"]
    est["blocks"]["activity"]["children"] = ["resources"]
    del est["blocks"]["steps"]
    del est["fields"]["STEP"]
    del est["formulas"]["ACTIVITY.stepped"]
    est["markers"] = {"START": {}, "END": {}}
    est["tags"]["parent"]["derived"] = ["RESOURCE", "START", "END"]
    del doc["prototypes"]["stepped"]
    del doc["prototypes"]["step"]


def _without_quantities(doc):
    est = doc["sheets"]["estimate"]
    est["not_shown"] = est.get("not_shown", []) + ["ELEMENT_QTY"]
    est["rows"] = ["ITEM", "GROUP"]
    del est["fields"]["ELEMENT_QTY"]
    del est["labels"]["ELEMENT_QTY"]
    del doc["prototypes"]["element_qty"]


def _doc(*changes):
    doc = copy.deepcopy(T.DECLARATION)
    for change in changes:
        change(doc)
    return doc


def _book(tmp_path, *changes):
    pack = TemplatePack(T.make(tmp_path / "pack", declaration=_doc(*changes)))
    book = tmp_path / "book.xlsx"
    pack.build(H.fixture_doc(), book, options={"exported_at": AT})
    return pack, book


def _row(ws, kind, ident):
    return next(r for r in range(T.FIRST, ws.max_row + 1)
                if ws[f"{T.KIND}{r}"].value == kind and ws[f"{T.ID}{r}"].value == ident)


def _block(ws, activity_id):
    """``(first, last)``: an activity's rows, its ACTIVITY row to its END."""
    first = _row(ws, "ACTIVITY", activity_id)
    last = next(r for r in range(first, ws.max_row + 1) if ws[f"{T.KIND}{r}"].value == "END")
    return first, last


# -- the loader ------------------------------------------------------------------

def test_a_kind_left_out_on_purpose_loads():
    for changes in ((_without_steps,), (_without_quantities,),
                    (_without_steps, _without_quantities)):
        decl = D.load(_doc(*changes))
        assert decl.sheets["estimate"].not_shown == tuple(
            k for c, k in ((_without_steps, "STEP"), (_without_quantities, "ELEMENT_QTY"))
            if c in changes)


def test_the_shipped_declarations_show_every_kind():
    assert D.load(T.DECLARATION).sheets["estimate"].not_shown == ()


def _also(change):
    def both(doc):
        _without_steps(doc)
        change(doc)
    return both


@pytest.mark.parametrize("change, says", [
    # A kind the sheet holds no rows of.
    (lambda d: d["sheets"]["estimate"].update(not_shown=["MEMBER"]),
     r"sheets\.estimate\.not_shown: MEMBER is not a kind this sheet holds \(it may leave "
     r"out: STEP, RESOURCE, ELEMENT_QTY\)"),
    (lambda d: d["sheets"]["bid"].update(not_shown=["ELEMENT_QTY"]),
     r"sheets\.bid\.not_shown: ELEMENT_QTY is not a kind this sheet holds"),
    # Said not shown, and shown all the same.
    (lambda d: d["sheets"]["estimate"].update(not_shown=["STEP"]),
     r"sheets\.estimate\.not_shown: STEP is shown on this sheet"),
    (_also(lambda d: d["sheets"]["estimate"]["fields"].update(STEP={"name": "B"})),
     r"sheets\.estimate\.not_shown: STEP is shown on this sheet"),
    # A prototype the fill or an insert would place the kind from.
    (_also(lambda d: d["prototypes"].update(step="mb.tpl.step")),
     r"prototypes\.step: STEP is not shown on sheets\.estimate"),
    (_also(lambda d: d["prototypes"].update(stepped="mb.tpl.stepped")),
     r"prototypes\.stepped: STEP is not shown on sheets\.estimate"),
])
def test_a_not_shown_kind_must_be_one_the_sheet_holds_and_left_out_whole(change, says):
    with pytest.raises(D.DeclarationError, match=says):
        D.load(_doc(change))


def test_a_crew_block_cannot_leave_out_its_members():
    """A crew's only child is its members: an owner block still needs one."""
    def change(doc):
        crews = doc["sheets"]["crews"]
        crews["not_shown"] = ["MEMBER"]
        del crews["blocks"]["members"]
        crews["blocks"]["crew"]["children"] = []
        del crews["fields"]
        del doc["prototypes"]["member"]
    with pytest.raises(D.DeclarationError, match="an owner block needs a child block"):
        D.load(_doc(change))


def test_leaving_a_kind_out_unsaid_is_still_refused():
    def change(doc):
        _without_steps(doc)
        del doc["sheets"]["estimate"]["not_shown"]
    with pytest.raises(D.DeclarationError, match="name STEP in not_shown"):
        D.load(_doc(change))


# -- the reader ------------------------------------------------------------------

@pytest.mark.parametrize("changes", [(_without_steps,), (_without_quantities,),
                                     (_without_steps, _without_quantities)])
def test_a_book_that_leaves_a_kind_out_builds_and_reads_clean(tmp_path, changes):
    """The build reads its book back before it writes (the fill's
    verification): no baseline step or element quantity reads as deleted."""
    pack, book = _book(tmp_path, *changes)
    assert pack.read(book).change_set.ops == []
    ws = H.open_book(book)[T.TAB]
    kinds = {ws[f"{T.KIND}{r}"].value for r in range(T.FIRST, ws.max_row + 1)}
    if _without_steps in changes:
        assert not kinds & {"STEP", "STEPS"}
    if _without_quantities in changes:
        assert "ELEMENT_QTY" not in kinds


def test_a_book_without_steps_reads_its_other_edits(tmp_path):
    pack, book = _book(tmp_path, _without_steps)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    ws[f"C{_row(ws, 'RESOURCE', 5)}"] = 7                 # a line of the stepped activity
    H.save_book(wb, book)
    (op,) = pack.read(book).change_set.ops
    assert (op["op"], op["ref"], op["fields"]) == ("resource.update", 5, {"quantity": "7"})


def test_a_stepped_activitys_shifts_cannot_be_edited_where_steps_are_not_shown(tmp_path):
    pack, book = _book(tmp_path, _without_steps)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    row = _row(ws, "ACTIVITY", 4)                         # Prep: one step
    ws[f"D{row}"] = 9
    H.save_book(wb, book)
    with pytest.raises(ReadRefused) as exc:
        read_book(book, pack=pack)
    assert [(p.row, p.column, p.message) for p in exc.value.problems] == [
        (row, "D", HIDDEN_STEPS)]


def test_a_stepless_activitys_shifts_are_still_sent(tmp_path):
    pack, book = _book(tmp_path, _without_steps)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    ws[f"D{_row(ws, 'ACTIVITY', 1)}"] = 4                  # Excavate: no steps
    H.save_book(wb, book)
    (op,) = pack.read(book).change_set.ops
    assert (op["op"], op["ref"], op["fields"]) == ("activity.update", 1,
                                                   {"duration_shifts": "4"})


def test_a_copied_stepped_activity_says_it_loses_its_steps(tmp_path):
    pack, book = _book(tmp_path, _without_steps)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    first, last = _block(ws, 4)
    H.insert_copies(ws, first, last, last + 1)
    H.save_book(wb, book)
    cs = pack.read(book).change_set
    assert [op["op"] for op in cs.ops] == ["activity.create", "activity.update",
                                           "resource.create", "resource.create"]
    assert cs.ops[1]["fields"] == {"duration_shifts": "2"}   # stepless, at the shifts it showed
    assert any("the copy of activity 4 is created without its steps, which this book does "
               "not show" in note for note in cs.notes)


def test_a_row_typed_above_an_activitys_lines_is_stray_not_a_first_step(tmp_path):
    pack, book = _book(tmp_path, _without_steps)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    row = _row(ws, "ACTIVITY", 1) + 1                     # between Excavate and its START
    H.type_row(ws, row, {"B": "Stray", "C": 1})
    H.save_book(wb, book)
    with pytest.raises(ReadRefused) as exc:
        read_book(book, pack=pack)
    assert [(p.row, p.message) for p in exc.value.problems] == [(row, STRAY)]


# -- the refresh -----------------------------------------------------------------

def test_a_book_without_steps_refreshes_past_server_steps(tmp_path):
    """A step BidSheet.ai added, changed or deleted -- an activity's first
    step among them -- is nothing this book holds."""
    pack, book = _book(tmp_path, _without_steps)
    fresh = H.fixture_doc()
    acts = {a["id"]: a for a in fresh["activities"]}
    acts[4]["steps"][0].update(duration="3.00", v="3" * 16)
    acts[5]["steps"] = [dict(acts[4]["steps"][0], id=50, name="Server step", v="5" * 16)]
    report = pack.refresh(book, fresh)
    assert report.clean and report.structural == [] and report.baseline_replaced
    assert pack.read(book).change_set.ops == []


def test_a_book_without_quantities_refreshes_past_server_quantities(tmp_path):
    pack, book = _book(tmp_path, _without_quantities)
    fresh = H.fixture_doc()
    element = fresh["elements"][0]
    element["quantities"].append(dict(element["quantities"][0], key="formwork_sf",
                                      v="7" * 16))
    report = pack.refresh(book, fresh)
    assert report.clean and report.structural == [] and report.baseline_replaced
    assert pack.read(book).change_set.ops == []


# -- a stepped activity's Shifts is an ordinary input where steps are not shown --

def test_a_copy_whose_shifts_was_edited_is_the_copy_not_the_original(tmp_path):
    """Steps not shown: Shifts is an input like any other, so the block
    whose Shifts differs from the baseline is the copy, and the unedited
    one stays the original (no HIDDEN_STEPS on the row meant as the copy)."""
    pack, book = _book(tmp_path, _without_steps)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    first, last = _block(ws, 4)                            # Prep: one step
    H.insert_copies(ws, first, last, last + 1)
    ws[f"D{first}"] = 9                                    # the first block's Shifts
    H.save_book(wb, book)
    cs = pack.read(book).change_set
    assert [op["op"] for op in cs.ops] == ["activity.create", "activity.update",
                                           "resource.create", "resource.create"]
    assert cs.ops[1]["ref"] == cs.ops[0]["ref"]
    assert cs.ops[1]["fields"] == {"duration_shifts": "9"}


def _linked_prep(tmp_path):
    """The mini-book without steps, its stepped Prep linked to element 1."""
    doc = H.fixture_doc()
    next(a for a in doc["activities"] if a["id"] == 4)["element_ids"] = [1]
    pack = TemplatePack(T.make(tmp_path / "pack", declaration=_doc(_without_steps)))
    book = tmp_path / "book.xlsx"
    pack.build(doc, book, options={"exported_at": AT})
    return pack, book


def test_linked_copies_differing_only_in_shifts_are_refused(tmp_path):
    pack, book = _linked_prep(tmp_path)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    first, last = _block(ws, 4)
    H.insert_copies(ws, first, last, last + 1)
    ws[f"D{last + 1}"] = 9                                 # the second block's Shifts
    H.save_book(wb, book)
    with pytest.raises(ReadRefused) as exc:
        read_book(book, pack=pack)
    assert any("activity 'Prep' is linked to elements/spreads" in p.message
               for p in exc.value.problems)
