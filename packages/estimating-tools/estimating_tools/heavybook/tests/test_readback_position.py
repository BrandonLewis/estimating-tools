"""A created activity or line keeps the place the estimator gave it (#458):
its create sends a ``sort_order`` that sorts it there among its siblings'
current orders (rows list by ``(sort_order, id)``; a created row's id is the
highest; BidSheet.ai never renumbers siblings), and where siblings tie so no
order fits, the siblings below are renumbered (``reader.place``)."""
from __future__ import annotations

from estimating_tools.heavybook.columns import CR
from estimating_tools.heavybook.tests import _readback as H

PUMP = {CR.DESC: "Pump", CR.QTY: 2, CR.UCOST: 80, CR.TYPE: "equipment"}


def _doc(orders=None, activities=None):
    """The fixture with resources' (``orders``) and activities'
    (``activities``) sort orders set, ``{id: sort_order}``. As built, every
    line is at 0 -- Walls' Carpenters (2) and Foreman (3) tie."""
    doc = H.fixture_doc()
    for res in doc["resources"]:
        res["sort_order"] = (orders or {}).get(res["id"], res["sort_order"])
    for a in doc["activities"]:
        a["sort_order"] = (activities or {}).get(a["id"], a["sort_order"])
    return doc


def _book(tmp_path, doc):
    return H.build_book(doc, tmp_path / "book.xlsx")


def _edit(path, fn):
    wb = H.open_book(path)
    fn(wb, wb[H.CR_TAB])
    H.save_book(wb, path)


def _creates(cs, name="resource.create"):
    return [op["fields"].get("sort_order") for op in H.ops_named(cs, name)]


def _bumps(cs, name="resource.update"):
    return [(op["ref"], op["fields"]) for op in H.ops_named(cs, name)]


# -- lines -----------------------------------------------------------------------

def test_a_typed_line_between_two_spaced_lines_takes_the_one_above(tmp_path):
    path = _book(tmp_path, _doc({2: 10, 3: 20}))
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    cs = H.read(path)
    assert _creates(cs) == [10] and _bumps(cs) == []


def test_a_line_between_adjacent_orders_sorts_after_the_one_above_by_id(tmp_path):
    """Orders 1 and 2 leave no integer between them, but none is needed: the
    new line takes 1 and its id, the highest, sorts it after Carpenters."""
    path = _book(tmp_path, _doc({2: 1, 3: 2}))
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    cs = H.read(path)
    assert _creates(cs) == [1] and _bumps(cs) == []


def test_a_typed_line_between_tied_lines_renumbers_the_one_below(tmp_path):
    """Carpenters and Foreman are both 0 (Foreman after it by id): no order
    puts the new line between them, so Foreman is renumbered to 1."""
    path = _book(tmp_path, _doc())
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    cs = H.read(path)
    assert [op["op"] for op in cs.ops] == ["resource.create", "resource.update"]
    assert _creates(cs) == [0]
    (update,) = H.ops_named(cs, "resource.update")
    assert update["ref"] == 3 and update["fields"] == {"sort_order": 1} and "v" in update
    wb = H.open_book(path)
    foreman = H.cr_row(wb[H.CR_TAB], "RESOURCE", 3)
    assert {"op_index": 1, "sheet": H.CR_TAB, "row": foreman} in cs.rows
    assert f"Cost Report row {foreman}: 'Foreman' sort_order 0 → 1" in cs.summary
    assert any(n.startswith(f"Cost Report row {foreman}:") and "renumbered" in n
               for n in cs.notes)


def test_renumbering_stops_where_a_gap_opens(tmp_path):
    """Three tied lines then a spaced one: only the tied ones below the new
    line move, each to the least order that keeps it after the row above."""
    doc = _doc({2: 0, 3: 0})
    doc["resources"] += [
        dict(doc["resources"][2], id=20, name="Laborer", sort_order=0, v="a" * 16),
        dict(doc["resources"][2], id=21, name="Oiler", sort_order=5, v="b" * 16)]
    path = _book(tmp_path, doc)
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    cs = H.read(path)
    assert _creates(cs) == [0]
    assert _bumps(cs) == [(3, {"sort_order": 1}), (20, {"sort_order": 2})]


def test_a_renumbered_line_with_an_edit_gets_one_update(tmp_path):
    path = _book(tmp_path, _doc())

    def edit(wb, ws):
        ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 3)}"] = 7
        H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
            CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"})
    _edit(path, edit)
    cs = H.read(path)
    assert _bumps(cs) == [(3, {"quantity": "7", "sort_order": 1})]


def test_a_line_appended_at_the_end_takes_the_last_lines_order(tmp_path):
    path = _book(tmp_path, _doc({2: 3, 3: 4}))

    def insert(wb, ws):
        r = H.insert_template(wb, "hc.tpl.resource", H.CR_TAB, H.block_end(ws, 2))
        for letter, value in PUMP.items():
            ws[f"{letter}{r}"] = value
    _edit(path, insert)
    cs = H.read(path)
    assert _creates(cs) == [4] and _bumps(cs) == []


def test_a_line_appended_after_tied_lines_needs_no_renumbering(tmp_path):
    path = _book(tmp_path, _doc())
    _edit(path, lambda wb, ws: H.type_row(ws, H.block_end(ws, 2), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    cs = H.read(path)
    assert _creates(cs) == [0] and _bumps(cs) == []


def test_a_line_above_the_first_takes_one_less(tmp_path):
    path = _book(tmp_path, _doc({2: 0, 3: 1}))
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 2), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    cs = H.read(path)
    assert _creates(cs) == [-1] and _bumps(cs) == []


def test_a_pasted_line_mid_block_takes_the_one_above(tmp_path):
    path = _book(tmp_path, _doc({2: 10, 3: 20}))

    def paste(wb, ws):
        src = H.cr_row(ws, "RESOURCE", 1)
        new = H.insert_copies(ws, src, src, H.cr_row(ws, "RESOURCE", 3))
        ws[f"{CR.ID}{new}"] = 9999
        ws[f"{CR.V}{new}"] = "0123456789abcdef"
        ws[f"{CR.DESC}{new}"] = "Pump"
    _edit(path, paste)
    cs = H.read(path)
    assert _creates(cs) == [10] and _bumps(cs) == []


def test_a_copied_line_mid_block_takes_the_one_above(tmp_path):
    path = _book(tmp_path, _doc({2: 10, 3: 20}))

    def copy(wb, ws):
        src = H.cr_row(ws, "RESOURCE", 2)
        H.insert_copies(ws, src, src, H.cr_row(ws, "RESOURCE", 3))
    _edit(path, copy)
    cs = H.read(path)
    assert _creates(cs) == [10] and _bumps(cs) == []


def test_two_lines_typed_together_keep_their_order(tmp_path):
    path = _book(tmp_path, _doc({2: 10, 3: 20}))

    def typed(wb, ws):
        at = H.cr_row(ws, "RESOURCE", 3)
        H.type_row(ws, at, {CR.DESC: "Pump B", CR.QTY: 1, CR.UCOST: 2, CR.TYPE: "equipment"})
        H.type_row(ws, at, {CR.DESC: "Pump A", CR.QTY: 1, CR.UCOST: 1, CR.TYPE: "equipment"})
    _edit(path, typed)
    cs = H.read(path)
    assert [op["fields"]["name"] for op in H.ops_named(cs, "resource.create")] == [
        "Pump A", "Pump B"]
    assert _creates(cs) == [10, 10] and _bumps(cs) == []


def test_a_line_above_a_tied_allocation_posted_line_is_refused(tmp_path):
    """Rule 6: an allocation-posted line is never written, so it can't be
    renumbered to make room."""
    from estimating_tools.exchange.reader import ReadRefused
    from estimating_tools.exchange.reader.ops import MANAGED_ORDER
    import pytest

    doc = _doc()
    next(r for r in doc["resources"] if r["id"] == 3)["managed_by"] = "allocation"
    path = _book(tmp_path, doc)
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    with pytest.raises(ReadRefused) as exc:
        H.read(path)
    assert [p.message for p in exc.value.problems] == [MANAGED_ORDER]


# -- activities ------------------------------------------------------------------

def _copy_prep_above_pour(wb, ws):
    first = H.cr_row(ws, "ACTIVITY", 4)
    last = H.cr_row(ws, "END", parent=4, start=first)
    H.insert_copies(ws, first, last, H.cr_row(ws, "ACTIVITY", 5))


def test_a_copied_activity_takes_its_place_among_its_items_roots(tmp_path):
    """Prep (3) copied above Pour (4): the copy sorts with Prep."""
    path = _book(tmp_path, _doc())
    _edit(path, _copy_prep_above_pour)
    cs = H.read(path)
    assert _creates(cs, "activity.create") == [3]
    assert _bumps(cs, "activity.update") == []


def test_a_copied_activity_between_tied_roots_renumbers_the_one_below(tmp_path):
    path = _book(tmp_path, _doc(activities={4: 3, 5: 3}))
    _edit(path, _copy_prep_above_pour)
    cs = H.read(path)
    assert _creates(cs, "activity.create") == [3]
    assert [(ref, f) for ref, f in _bumps(cs, "activity.update") if "sort_order" in f] == [
        (5, {"sort_order": 4})]


def test_a_copied_child_takes_its_place_among_its_parents_children(tmp_path):
    """Ties (Walls' only child, 1) copied below itself, under Walls."""
    path = _book(tmp_path, _doc())

    def copy(wb, ws):
        first = H.cr_row(ws, "ACTIVITY", 3)
        last = H.cr_row(ws, "END", parent=3, start=first)
        H.insert_copies(ws, first, last, last + 1)
    _edit(path, copy)
    cs = H.read(path)
    (create,) = H.ops_named(cs, "activity.create")
    assert create["fields"]["parent_id"] == 2 and create["fields"]["sort_order"] == 1


def test_lines_of_a_copied_activity_sort_in_sheet_order(tmp_path):
    path = _book(tmp_path, _doc())

    def copy(wb, ws):
        first = H.cr_row(ws, "ACTIVITY", 2)
        last = H.cr_row(ws, "END", parent=2, start=first)
        H.insert_copies(ws, first, last, H.cr_row(ws, "ACTIVITY", 4))
    _edit(path, copy)
    cs = H.read(path)
    lines = [op for op in H.ops_named(cs, "resource.create")
             if op["fields"]["activity_id"] == "new:a1"]
    assert [op["fields"]["name"] for op in lines] == ["Carpenters", "Foreman"]
    assert [op["fields"]["sort_order"] for op in lines] == [0, 0]
    assert _bumps(cs) == []


def test_each_renumbered_line_in_a_chain_is_noted_without_naming_a_row(tmp_path):
    """Two tied lines below the new one are both renumbered: Laborer moves
    for Foreman, not for the new row, so the note names neither."""
    from estimating_tools.exchange.reader.ops import RENUMBERED

    doc = _doc()
    doc["resources"].append(
        dict(doc["resources"][2], id=20, name="Laborer", sort_order=0, v="a" * 16))
    path = _book(tmp_path, doc)
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    cs = H.read(path)
    assert _bumps(cs) == [(3, {"sort_order": 1}), (20, {"sort_order": 2})]
    ws = H.open_book(path)[H.CR_TAB]
    assert [n for n in cs.notes if "renumbered" in n] == [
        f"Cost Report row {H.cr_row(ws, 'RESOURCE', 3)}: "
        + RENUMBERED.format(what="'Foreman'", before=0, after=1),
        f"Cost Report row {H.cr_row(ws, 'RESOURCE', 20)}: "
        + RENUMBERED.format(what="'Laborer'", before=0, after=2)]
    assert all("a new row above keeps its place" in n for n in cs.notes if "renumbered" in n)


# -- existing rows reordered -----------------------------------------------------

def test_a_line_moved_within_its_activity_is_noted_and_not_sent(tmp_path):
    """Foreman cut above Carpenters: no op moves an existing row, so the read
    says BidSheet.ai keeps its order."""
    from estimating_tools.exchange.reader.ops import REORDERED

    path = _book(tmp_path, _doc({2: 10, 3: 20}))

    def cut(wb, ws):
        r = H.cr_row(ws, "RESOURCE", 3)
        H.cut_rows(ws, r, r, H.cr_row(ws, "RESOURCE", 2))
    _edit(path, cut)
    cs = H.read(path)
    assert cs.ops == []
    foreman = H.cr_row(H.open_book(path)[H.CR_TAB], "RESOURCE", 3)
    assert cs.notes == [f"Cost Report row {foreman}: " + REORDERED.format(what="'Foreman'")]


def test_an_activity_moved_among_its_items_roots_is_noted_and_not_sent(tmp_path):
    from estimating_tools.exchange.reader.ops import REORDERED

    path = _book(tmp_path, _doc())

    def cut(wb, ws):
        first = H.cr_row(ws, "ACTIVITY", 5)
        H.cut_rows(ws, first, H.block_end(ws, 5), H.cr_row(ws, "ACTIVITY", 4))
    _edit(path, cut)
    cs = H.read(path)
    assert cs.ops == []
    pour = H.cr_row(H.open_book(path)[H.CR_TAB], "ACTIVITY", 5)
    assert cs.notes == [f"Cost Report row {pour}: "
                        + REORDERED.format(what="activity 'Pour'")]


def test_a_renumbering_read_has_no_reorder_note(tmp_path):
    from estimating_tools.exchange.reader.ops import REORDERED

    path = _book(tmp_path, _doc())
    _edit(path, lambda wb, ws: H.type_row(ws, H.cr_row(ws, "RESOURCE", 3), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"}))
    marker = REORDERED.format(what="").split("--")[0].strip()
    assert not [n for n in H.read(path).notes if marker in n]


# -- activities: Navigator inserts and moves -------------------------------------

def test_a_navigator_activity_among_tied_roots_renumbers_the_roots_below(tmp_path):
    """Every root of item 1 at 0: a new activity inserted above Prep takes
    Walls' 0, and Prep and Pour are renumbered 1 and 2."""
    path = _book(tmp_path, _doc(activities={1: 0, 2: 0, 4: 0, 5: 0}))

    def insert(wb, ws):
        at = H.insert_template(wb, "hc.tpl.activity", H.CR_TAB, H.cr_row(ws, "ACTIVITY", 4))
        ws[f"{CR.DESC}{at}"] = "Dewater"
    _edit(path, insert)
    cs = H.read(path)
    assert _creates(cs, "activity.create") == [0]
    assert _bumps(cs, "activity.update") == [(4, {"sort_order": 1}), (5, {"sort_order": 2})]
    assert all("v" in op for op in H.ops_named(cs, "activity.update"))


def test_a_moved_activity_renumbered_for_a_copy_gets_one_update(tmp_path):
    """Finish (item 2) cut to the end of item 1, where Prep, Pour and Finish
    tie at 3; Prep copied above Pour. Pour and Finish are renumbered, and
    Finish's renumbering rides on the one update that carries its edit,
    after its move; both check the ``v`` the book read."""
    path = _book(tmp_path, _doc(activities={5: 3, 6: 3}))

    def edit(wb, ws):
        first = H.cr_row(ws, "ACTIVITY", 6)
        H.cut_rows(ws, first, H.block_end(ws, 6), H.block_end(ws, 5) + 1)
        ws[f"{CR.COUNT}{H.cr_row(ws, 'ACTIVITY', 6)}"] = 2
        _copy_prep_above_pour(wb, ws)
    _edit(path, edit)
    cs = H.read(path)
    finish = [op for op in cs.ops if op["ref"] == 6]
    assert [(op["op"], op["fields"]) for op in finish] == [
        ("activity.move", {"item_id": 1}),
        ("activity.update", {"count": 2, "sort_order": 5})]
    assert finish[0]["v"] == finish[1]["v"]
    assert _creates(cs, "activity.create") == [3]
    assert (5, {"sort_order": 4}) in _bumps(cs, "activity.update")
