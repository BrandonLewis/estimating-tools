"""Refresh against edits made the way Excel makes them (the PR #446 review's
scenarios): rows inserted and deleted through the writer's row ops, which
shift every formula as Excel does (openpyxl's own insert and delete do not),
next to server changes on the same, adjacent and copied rows."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from estimating_tools.exchange import rowops, writer
from estimating_tools.exchange.refresh import merge
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import BF, CK, CR, CW
from estimating_tools.heavybook.declaration import generate
from estimating_tools.heavybook.tests import _readback as H

#: The sheets the declaration does not bind: a delete may leave them #REF!.
DISPLAY = {"Checks", "Flat", "Recap", "Schedule"}
TYPED = {CR.DESC: "Typed pump", CR.QTY: 4, CR.UNIT: "HR", CR.UCOST: 25, CR.TYPE: "equipment"}


def _book(tmp_path, name="e1.xlsx"):
    return H.build_book(H.fixture_doc(), tmp_path / name)


def _fresh(changes=None, drop=(), doc=None):
    """The fixture payload with resources changed (``{id: {field: value}}``,
    each with a new ``v``) or dropped on the server."""
    doc = doc or H.fixture_doc()
    doc["resources"] = [r for r in doc["resources"] if r["id"] not in drop]
    for r in doc["resources"]:
        if r["id"] in (changes or {}):
            r.update(changes[r["id"]])
            r["v"] = f"{r['id']:016x}"
    return doc


def _added(doc, act=2, rid=10, name="Gravel"):
    """Resource ``rid``, a material line, added on the server to ``act``."""
    res = dict(next(r for r in H.fixture_doc()["resources"] if r["id"] == 2))
    res.update({"id": rid, "activity_id": act, "name": name, "component_type": "material",
                "quantity": "2.000", "unit_cost": "10.00", "labor_rate_id": None,
                "sort_order": 5, "v": "aaaaaaaaaaaaaaaa", "cost": "20.00"})
    doc["resources"].append(res)
    return doc


def _ops(path):
    result = hb_pack.pack().read(path)
    assert not result.problems, result.problems
    return [(o["op"], o["ref"], o.get("fields")) for o in result.change_set.ops]


def _row(path, kind, ident=None, parent=None):
    return H.cr_row(H.open_book(path)[H.CR_TAB], kind, ident, parent=parent)


def _set(path, kind, ident, col, value):
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{col}{H.cr_row(ws, kind, ident)}"] = value
    H.save_book(wb, path)


def _excel_delete(path, kind, ident):
    """Excel's row delete: every reference moves, a reference to the row
    itself reads #REF!."""
    writer.edit(path, rows=[rowops.DeleteRows(sheet=H.CR_TAB, first=_row(path, kind, ident))],
                lost_ok=DISPLAY)


def _excel_insert(path, before):
    """Excel's whole-row insert of a resource row above ``before`` (the
    Navigator's Insert, from the resource prototype). Returns ``before``."""
    first, last = H.template_rows(H.open_book(path), "hc.tpl.resource")
    writer.edit(path, rows=[rowops.InsertRows(sheet=H.CR_TAB, before=before,
                                              source="_templates", first=first, last=last)])
    return before


def _excel_type_resource(path, act, values=TYPED):
    """A resource typed into a row inserted above ``act``'s END."""
    row = _excel_insert(path, _row(path, "END", parent=act))
    wb = H.open_book(path)
    for letter, value in values.items():
        wb[H.CR_TAB][f"{letter}{row}"] = value
    H.save_book(wb, path)
    return row


def _excel_copy_resource(path, rid, act):
    """Excel's Insert Copied Cells: resource ``rid``'s row copied above
    ``act``'s END (a row inserted, then the copy pasted into it)."""
    src = _row(path, "RESOURCE", rid)
    row = _excel_insert(path, _row(path, "END", parent=act))
    wb = H.open_book(path)
    H.copy_row(wb[H.CR_TAB], src + 1 if src >= row else src, row)
    H.save_book(wb, path)
    return row


def _excel_cut_resource(path, rid, act):
    """Excel's Insert Cut Cells, as a copy then a delete of the source."""
    _excel_copy_resource(path, rid, act)
    rows = [r for r in range(1, H.open_book(path)[H.CR_TAB].max_row + 1)
            if H.open_book(path)[H.CR_TAB][f"{CR.ID}{r}"].value == rid
            and H.open_book(path)[H.CR_TAB][f"{CR.KIND}{r}"].value == "RESOURCE"]
    writer.edit(path, rows=[rowops.DeleteRows(sheet=H.CR_TAB, first=rows[0])], lost_ok=DISPLAY)


def _refresh(path, fresh, **kw):
    return hb_pack.pack().refresh(path, fresh, **kw)


# -- the same row, adjacent rows -----------------------------------------------------------

def test_a_row_level_collision_lists_every_field_that_differs(tmp_path):
    path = _book(tmp_path)
    _set(path, "RESOURCE", 2, CR.QTY, 3)
    before = path.read_bytes()
    report = _refresh(path, _fresh({2: {"unit_cost": "410.00"}}))
    text = [str(c) for c in report.collisions]
    assert len(text) == 2
    assert any("Quantity: BidSheet.ai 2, this book 3 (built with 2)" in t for t in text)
    assert any("Unit cost: BidSheet.ai 410, this book 400 (built with 400)" in t for t in text)
    assert path.read_bytes() == before


@pytest.mark.parametrize("server", ["3.000", "3.0000000000000004"])
def test_the_same_number_on_both_sides_is_convergent(tmp_path, server):
    path = _book(tmp_path)
    _set(path, "RESOURCE", 2, CR.QTY, 3)
    report = _refresh(path, _fresh({2: {"quantity": server}}))
    assert report.clean and report.baseline_replaced
    assert _ops(path) == []


def test_one_field_alike_and_another_changed_on_the_server_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _set(path, "RESOURCE", 2, CR.QTY, 3)
    report = _refresh(path, _fresh({2: {"quantity": "3.000", "unit_cost": "410.00"}}))
    (collision,) = report.collisions
    assert "Unit cost: BidSheet.ai 410, this book 400" in str(collision)


def test_a_server_change_the_book_does_not_show_keeps_the_books_edit(tmp_path):
    path = _book(tmp_path)
    _set(path, "RESOURCE", 2, CR.QTY, 3)
    report = _refresh(path, _fresh({2: {"description": "server note"}}))
    assert report.clean
    assert _ops(path) == [("resource.update", 2, {"quantity": "3"})]


def test_an_adjacent_server_change_is_written_beside_the_books_edit(tmp_path):
    path = _book(tmp_path)
    _set(path, "RESOURCE", 2, CR.QTY, 3)
    report = _refresh(path, _fresh({3: {"quantity": "7.000"}}))
    assert report.clean
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 3)}"].value == 7
    assert _ops(path) == [("resource.update", 2, {"quantity": "3"})]


# -- copies, cuts and deletes -------------------------------------------------------------

@pytest.mark.parametrize("server, says", [
    ({2: {"quantity": "5.000"}}, "changed in BidSheet.ai and copied in this book"),
    ({2: {"description": "server note"}}, "changed in BidSheet.ai and copied in this book"),
    ({2: {"activity_code_id": 7}}, "changed in BidSheet.ai and copied in this book"),
])
def test_a_server_change_to_a_copied_row_is_a_collision(tmp_path, server, says):
    path = _book(tmp_path)
    _excel_copy_resource(path, 2, 2)
    ops = _ops(path)
    assert [o[0] for o in ops] == ["resource.create"]
    before = path.read_bytes()
    report = _refresh(path, _fresh(server))
    (collision,) = report.collisions
    assert says in str(collision)
    assert path.read_bytes() == before


def test_a_server_delete_of_a_copied_row_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _excel_copy_resource(path, 2, 2)
    report = _refresh(path, _fresh(drop=(2,)))
    (collision,) = report.collisions
    assert "deleted in BidSheet.ai, copied in this book" in str(collision)


def test_a_server_change_to_a_cut_row_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _excel_cut_resource(path, 2, 5)
    assert sorted(o[0] for o in _ops(path)) == ["resource.create", "resource.delete"]
    before = path.read_bytes()
    report = _refresh(path, _fresh({2: {"quantity": "5.000"}}))
    (collision,) = report.collisions
    assert "changed in BidSheet.ai (quantity) and deleted in this book" in str(collision)
    assert path.read_bytes() == before


def test_a_server_change_beside_a_cut_row_is_written(tmp_path):
    path = _book(tmp_path)
    _excel_cut_resource(path, 2, 5)
    ops = _ops(path)
    report = _refresh(path, _fresh({3: {"quantity": "7.000"}}))
    assert report.clean
    assert _ops(path) == ops


def test_a_server_change_to_a_row_the_book_deleted_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _excel_delete(path, "RESOURCE", 3)
    before = path.read_bytes()
    report = _refresh(path, _fresh({3: {"quantity": "7.000"}}))
    (collision,) = report.collisions
    assert "line 'Foreman': changed in BidSheet.ai (quantity) and deleted in this book" in str(
        collision)
    assert path.read_bytes() == before


def test_a_row_deleted_on_both_sides_is_convergent(tmp_path):
    path = _book(tmp_path)
    _excel_delete(path, "RESOURCE", 3)
    report = _refresh(path, _fresh(drop=(3,)))
    assert report.clean and report.baseline_replaced
    assert _ops(path) == []


def test_a_server_change_beside_a_row_the_book_deleted_is_written(tmp_path):
    path = _book(tmp_path)
    _excel_delete(path, "RESOURCE", 3)
    report = _refresh(path, _fresh({2: {"quantity": "9.000"}}))
    assert report.clean
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 2)}"].value == 9
    assert _ops(path) == [("resource.delete", 3, {})]


# -- typed rows next to rows the server added -------------------------------------------

@pytest.mark.parametrize("typed_in", [2, 1, 5])
def test_server_added_rows_land_beside_typed_rows(tmp_path, typed_in):
    path = _book(tmp_path)
    _excel_type_resource(path, typed_in)
    ops = _ops(path)
    report = _refresh(path, _added(_fresh(drop=(3,))))
    assert report.clean and report.rows_added == 1 and report.rows_removed == 1
    ws = H.open_book(path)[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 10)
    assert ws[f"{CR.KIND}{row + 1}"].value == "END" and ws[f"{CR.ID}{row}"].value == 10
    assert any(ws[f"{CR.DESC}{r}"].value == "Typed pump" for r in range(1, ws.max_row + 1))
    assert _ops(path) == ops


def test_typed_rows_edits_and_server_rows_all_at_once(tmp_path):
    path = _book(tmp_path)
    _excel_type_resource(path, 2)
    _set(path, "RESOURCE", 2, CR.QTY, 3)
    ops = _ops(path)
    report = _refresh(path, _added(_fresh({1: {"quantity": "31.000"}}, drop=(3,))))
    assert report.clean
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 31
    with pytest.raises(LookupError):
        H.cr_row(ws, "RESOURCE", 3)
    assert _ops(path) == ops


def test_several_rows_added_in_several_blocks(tmp_path):
    path = _book(tmp_path)
    _excel_type_resource(path, 5)
    ops = _ops(path)
    fresh = _added(_added(_added(H.fixture_doc(), 5, 10, "Gravel"), 5, 11, "Sand"), 1, 12,
                   "Water")
    report = _refresh(path, fresh)
    assert report.clean and report.rows_added == 3
    assert any("line 'Water' added to activity 'Excavate' from BidSheet.ai" in w
               for w in report.written)
    assert any("Checks: 3 figure(s) BidSheet.ai has now have no row" in n for n in report.notes)
    ws = H.open_book(path)[H.CR_TAB]
    for rid in (10, 11, 12):
        H.cr_row(ws, "RESOURCE", rid)
    assert _ops(path) == ops


def test_written_rows_are_numbered_as_the_book_stands_after_the_refresh(tmp_path):
    path = _book(tmp_path)
    report = _refresh(path, _fresh({8: {"quantity": "2.000"}}, drop=(3,)))
    assert report.clean
    ws = H.open_book(path)[H.CR_TAB]
    fence = H.cr_row(ws, "RESOURCE", 8)
    assert any(w.startswith(f"{H.CR_TAB} row {fence}: line 'Fence sub' quantity")
               for w in report.written)
    assert any("line 'Foreman' removed" in w and "before the refresh" in w
               for w in report.written)


# -- the estimate, a step, an item's scope ----------------------------------------------

def _markup(value):
    def edit(wb):
        ws = wb[H.BF_TAB]
        ws[f"{BF.VALUE}{BF.ROWS['markup_percentage']}"] = value
    return edit


def _edit(path, fn):
    wb = H.open_book(path)
    fn(wb)
    H.save_book(wb, path)


def test_an_estimate_field_both_sides_set_alike_drops_out_of_the_op(tmp_path):
    path = _book(tmp_path)
    _edit(path, _markup(12))
    doc = H.fixture_doc()
    doc["estimate"].update({"markup_percentage": "12.00", "markup_amount": "300.00",
                            "v": "eeeeeeeeeeeeeeee"})
    report = _refresh(path, doc)
    assert report.clean
    assert _ops(path) == []


def test_an_estimate_field_only_the_book_set_stays_in_the_op(tmp_path):
    path = _book(tmp_path)
    _edit(path, _markup(12))
    doc = H.fixture_doc()
    doc["estimate"].update({"markup_amount": "300.00", "v": "eeeeeeeeeeeeeeee"})
    report = _refresh(path, doc)
    assert report.clean
    assert _ops(path) == [("estimate.update", 1, {"markup_percentage": "12"})]


def test_an_estimate_field_both_sides_set_differently_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _edit(path, _markup(12))
    doc = H.fixture_doc()
    doc["estimate"].update({"markup_percentage": "11.00", "v": "eeeeeeeeeeeeeeee"})
    (collision,) = _refresh(path, doc).collisions
    assert "BidSheet.ai 11, this book 12 (built with 10)" in str(collision)


def test_a_server_added_step_is_inserted_between_steps_and_start(tmp_path):
    path = _book(tmp_path)
    doc = H.fixture_doc()
    act = next(a for a in doc["activities"] if a["id"] == 4)
    step = dict(act["steps"][0], id=50, name="Server step", sort_order=9, v="5" * 16)
    act["steps"].append(step)
    report = _refresh(path, doc)
    assert report.clean and report.rows_added == 1
    assert any("step 'Server step' added to activity 'Prep'" in w for w in report.written)
    ws = H.open_book(path)[H.CR_TAB]
    row = H.cr_row(ws, "STEP", 50)
    assert ws[f"{CR.KIND}{row - 1}"].value == "STEP" and ws[f"{CR.KIND}{row + 1}"].value == "START"
    shifts = ws[f"{CR.SHIFTS}{H.cr_row(ws, 'ACTIVITY', 4)}"].value
    assert f"D{row - 2}:D{row + 1}" in shifts            # STEPS..START: the new step counts
    assert _ops(path) == []


def test_an_item_excluded_on_the_server_refreshes(tmp_path):
    path = _book(tmp_path)
    doc = H.fixture_doc()
    item = next(i for i in doc["items"] if i["id"] == 4)
    item.update({"scope": "excluded", "v": "1" * 16})
    report = _refresh(path, doc)
    assert report.clean
    assert _ops(path) == []


def test_an_item_brought_into_scope_on_the_server_needs_a_rebuild(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    doc = H.fixture_doc()
    item = next(i for i in doc["items"] if i["id"] == 5)
    item.update({"scope": "included", "v": "2" * 16})
    report = _refresh(path, doc)
    assert any("brought into scope" in s for s in report.structural)
    assert path.read_bytes() == before


# -- what the refresh expects the copy to send ------------------------------------------

def test_a_row_that_converged_but_also_moved_keeps_its_move():
    move = {"op": "activity.move", "ref": 2, "fields": {"item_id": 4}}
    update = {"op": "activity.update", "ref": 2, "fields": {"production_rate": "5"}}
    p = merge._Plan.__new__(merge._Plan)
    p.m = merge.Merge()
    p.ops = {("ACTIVITY", 2): [(0, move), (1, update)]}
    p.converge("ACTIVITY", 2)
    assert p.m.dropped == {1: None}
    assert ("ACTIVITY", 2) not in p.m.convergent
    assert merge.expected(SimpleNamespace(ops=[move, update]), p.m) == [merge.signature(move)]


def test_expected_drops_converged_fields_not_whole_ops():
    op = {"op": "estimate.update", "ref": 1,
          "fields": {"markup_percentage": "12", "indirect_cost": "5"}}
    m = merge.Merge(dropped={0: {"markup_percentage"}})
    assert merge.expected(SimpleNamespace(ops=[op]), m) == [
        merge.signature(dict(op, fields={"indirect_cost": "5"}))]
    m = merge.Merge(dropped={0: {"markup_percentage", "indirect_cost"}})
    assert merge.expected(SimpleNamespace(ops=[op]), m) == []


def test_a_refusal_names_the_ops_that_differ(tmp_path, monkeypatch):
    path = _book(tmp_path)
    _set(path, "RESOURCE", 2, CR.QTY, 3)
    before = path.read_bytes()
    monkeypatch.setattr(merge, "expected", lambda change_set, m: [])
    with pytest.raises(ValueError) as exc:
        _refresh(path, _fresh({1: {"quantity": "32.000"}}))
    assert "it would also send resource.update 2" in str(exc.value)
    assert "nothing written" in str(exc.value)
    assert path.read_bytes() == before


def test_a_save_during_the_refresh_is_not_overwritten(tmp_path, monkeypatch):
    from estimating_tools.exchange import refresh as refresh_mod

    path = _book(tmp_path)
    real = refresh_mod._accept

    def accept(tmp, pack, expected):
        why = real(tmp, pack, expected)
        _set(path, "RESOURCE", 2, CR.QTY, 3)          # the estimator saves meanwhile
        return why

    monkeypatch.setattr(refresh_mod, "_accept", accept)
    with pytest.raises(ValueError, match="changed while it was being refreshed"):
        _refresh(path, _fresh({1: {"quantity": "32.000"}}))
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 2)}"].value == 3
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 30
    assert not list(tmp_path.glob("*.patching.xlsx"))


# -- export values ---------------------------------------------------------------------

_KIND_COLS = {"cost_report": CR.KIND, "crews": CW.KIND, "bid_form": BF.KIND}


def _declared_export_values():
    for key, sheet in generate()["sheets"].items():
        for kind, letters in (sheet.get("export_values") or {}).items():
            for letter in letters:
                yield key, sheet["tab"], kind, letter


@pytest.mark.parametrize("key, tab, kind, letter", list(_declared_export_values()))
def test_every_declared_export_value_refuses_an_edit(tmp_path, key, tab, kind, letter):
    path = _book(tmp_path)
    wb = H.open_book(path)
    ws = wb[tab]
    row = next(r for r in range(1, ws.max_row + 1) if ws[f"{_KIND_COLS[key]}{r}"].value == kind)
    ws[f"{letter}{row}"] = 12345
    H.save_book(wb, path)
    result = hb_pack.pack().read(path)
    assert any(f"{tab} row {row} column {letter}" in str(p) and "read-only" in str(p)
               for p in result.problems), result.problems


# -- the Checks sheet ------------------------------------------------------------------

def _carpenters(path):
    ws = H.open_book(path)["Checks"]
    return [ws[f"{CK.BIDSHEET}{r}"].value for r in range(1, ws.max_row + 1)
            if ws[f"{CK.DESC}{r}"].value == "Carpenters"]


def test_checks_rows_that_read_alike_keep_their_own_figures(tmp_path):
    doc = H.fixture_doc()
    next(r for r in doc["resources"] if r["id"] == 9)["name"] = "Carpenters"
    path = H.build_book(doc, tmp_path / "e1.xlsx")
    assert _carpenters(path) == [1452, 100]
    fresh = H.fixture_doc()
    next(r for r in fresh["resources"] if r["id"] == 9).update(name="Carpenters", cost="150.00")
    next(r for r in fresh["resources"] if r["id"] == 1).update(quantity="31.000", v="1" * 16)
    assert _refresh(path, fresh).clean
    assert _carpenters(path) == [1452, 150]


# -- the Copilot review of PR #446 -------------------------------------------------------

def test_an_as_of_export_figure_a_formula_reads_is_refreshed(tmp_path):
    """The Bid Form's indirect cost is no input and no formula, but its
    markup total and bid factor read it."""
    from estimating_tools.estimate_spec.tests._formula_eval import evaluate

    path = _book(tmp_path)
    fresh = H.fixture_doc()
    fresh["estimate"]["totals"]["indirect_cost"] = "500.00"
    report = _refresh(path, fresh)
    assert report.clean
    ws = H.open_book(path)[H.BF_TAB]
    assert ws[f"{BF.VALUE}{BF.ROWS['indirect_cost']}"].value == 500
    assert _ops(path) == []
    rebuilt = H.build_book(fresh, tmp_path / "rebuilt.xlsx")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ours = evaluate(H.open_book(path), tmp_path / "a")
    theirs = evaluate(H.open_book(rebuilt), tmp_path / "b")
    for name in ("markup_total", "bid_factor"):
        ref = f"{H.BF_TAB}!{BF.VALUE}{BF.ROWS[name]}"
        assert ours[ref] == pytest.approx(theirs[ref]), name


def test_a_stamp_from_before_step_3_takes_the_hidden_bid_quantity(tmp_path):
    import json

    path = _book(tmp_path)
    wb = H.open_book(path)
    raw = json.loads(wb["_wb"]["A1"].value)
    del raw["declaration"]["sheets"]["cost_report"]["export_values"]["ITEM"]
    del raw["declaration"]["sheets"]["crews"]["export_values"]["MEMBER"]
    wb["_wb"]["A1"] = json.dumps(raw)
    H.save_book(wb, path)
    fresh = H.fixture_doc()
    next(i for i in fresh["items"] if i["id"] == 2)["schedule_quantity"] = "40.00"
    assert _refresh(path, fresh).clean
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.H1}{H.cr_row(ws, 'ITEM', 2)}"].value == 40
    raw = json.loads(H.open_book(path)["_wb"]["A1"].value)
    assert raw["declaration"]["sheets"]["cost_report"]["export_values"]["ITEM"] == {
        CR.H1: "schedule_quantity"}
    assert _ops(path) == []


def _excel_delete_block(path, first_activity, last_activity):
    """Excel's delete of whole activity blocks: from ``first_activity``'s row
    to ``last_activity``'s END."""
    first = _row(path, "ACTIVITY", first_activity)
    last = _row(path, "END", parent=last_activity)
    writer.edit(path, rows=[rowops.DeleteRows(sheet=H.CR_TAB, first=first,
                                              count=last - first + 1)],
                lost_ok=DISPLAY | {"_shares"})


def test_a_server_change_under_an_activity_the_book_deleted_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _excel_delete_block(path, 3, 3)
    assert ("activity.delete", 3, {}) in _ops(path)
    before = path.read_bytes()
    report = _refresh(path, _fresh({4: {"quantity": "9.000"}}))
    (collision,) = report.collisions
    assert "line 'Form ties': changed in BidSheet.ai (quantity) and deleted in this book" in str(
        collision)
    assert path.read_bytes() == before


def test_a_server_change_to_a_child_of_an_activity_the_book_deleted_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _excel_delete_block(path, 2, 3)                       # Walls and its child Ties
    fresh = H.fixture_doc()
    next(a for a in fresh["activities"] if a["id"] == 3).update(production_rate="9.00",
                                                                v="3" * 16)
    before = path.read_bytes()
    report = _refresh(path, fresh)
    assert any("activity 'Ties'" in str(c) and "deleted in this book" in str(c)
               for c in report.collisions)
    assert path.read_bytes() == before


def _member_count(path, member, count):
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    ws[f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', member)}"] = count
    H.save_book(wb, path)


def _server_roster(doc, crew_id, change):
    crew = next(c for c in doc["crews"] if c["id"] == crew_id)
    change(crew)
    for m, new_id in zip(crew["members"], range(11, 20)):
        m["id"] = new_id                                  # BidSheet.ai recreates members
    crew["v"] = "c" * 16
    return doc


def test_a_member_count_both_sides_set_alike_converges(tmp_path):
    path = _book(tmp_path)
    _member_count(path, 1, 3)
    assert [o[0] for o in _ops(path)] == ["crew.update_members"]
    fresh = _server_roster(H.fixture_doc(), 1,
                           lambda c: c["members"][0].update(count="3.00"))
    report = _refresh(path, fresh)
    assert report.clean and not report.collisions
    ws = H.open_book(path)[H.CW_TAB]
    assert [ws[f"{CW.ID}{r}"].value for r in (6, 7)] == [11, 12]
    assert _ops(path) == []


def test_a_member_both_sides_removed_converges(tmp_path):
    path = _book(tmp_path)
    row = H.cw_row(H.open_book(path)[H.CW_TAB], "MEMBER", 1)
    writer.edit(path, rows=[rowops.DeleteRows(sheet=H.CW_TAB, first=row)], lost_ok=DISPLAY)
    fresh = _server_roster(H.fixture_doc(), 1, lambda c: c["members"].pop(0))
    report = _refresh(path, fresh)
    assert report.clean and not report.collisions
    assert _ops(path) == []


def test_a_member_count_both_sides_set_differently_is_a_collision(tmp_path):
    path = _book(tmp_path)
    _member_count(path, 1, 3)
    fresh = _server_roster(H.fixture_doc(), 1,
                           lambda c: c["members"][0].update(count="4.00"))
    (collision,) = _refresh(path, fresh).collisions
    assert "members: BidSheet.ai has" in str(collision)


# -- the second review of PR #446 ------------------------------------------------------

def test_a_block_deleted_on_both_sides_needs_a_rebuild_only_for_its_cost_shares(tmp_path):
    """Walls and its child Ties deleted in the book (one activity.delete)
    and in BidSheet.ai: no "deleted in BidSheet.ai" for Ties. The shares the
    two paid are gone from the payload, and the _shares sheet holds constants,
    so the cost-share guard still asks for a rebuild."""
    path = _book(tmp_path)
    _excel_delete_block(path, 2, 3)
    fresh = H.fixture_doc()
    fresh["activities"] = [a for a in fresh["activities"] if a["id"] not in (2, 3)]
    fresh["resources"] = [x for x in fresh["resources"] if x["activity_id"] not in (2, 3)]
    fresh["shares"] = [s for s in fresh["shares"] if s["activity_id"] not in (2, 3)]
    report = _refresh(path, fresh)
    assert not report.collisions
    (only,) = report.structural
    assert "cost shares" in only


def test_a_typed_indirect_cost_replaced_by_the_refresh_is_noted(tmp_path):
    path = _book(tmp_path)
    _edit(path, lambda wb: wb[H.BF_TAB].__setitem__(f"{BF.VALUE}{BF.ROWS['indirect_cost']}", 999))
    fresh = H.fixture_doc()
    fresh["estimate"]["totals"]["indirect_cost"] = "500.00"
    report = _refresh(path, fresh)
    assert report.clean
    assert any("indirect_cost typed here (999) is replaced by BidSheet.ai's 500" in n
               for n in report.notes)
    assert H.open_book(path)[H.BF_TAB][f"{BF.VALUE}{BF.ROWS['indirect_cost']}"].value == 500


def test_a_member_both_sides_added_alike_converges(tmp_path):
    import copy

    path = _book(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    src, end = H.cw_row(ws, "MEMBER", 2, parent=1), H.cw_row(ws, "CREW_END", parent=1)
    H.insert_copies(ws, src, src, end)
    ws[f"{CW.COUNT}{end}"] = 2
    H.save_book(wb, path)

    def add(crew):
        extra = copy.deepcopy(crew["members"][1])
        extra.update(count="2.00", sort_order=extra["sort_order"] + 1)
        crew["members"].append(extra)

    report = _refresh(path, _server_roster(H.fixture_doc(), 1, add))
    assert report.clean
    assert _ops(path) == []


def test_a_roster_both_sides_set_alike_converges_in_another_order(tmp_path):
    path = _book(tmp_path)
    _member_count(path, 1, 3)

    def change(crew):
        crew["members"][0]["count"] = "3.00"
        crew["members"][0]["sort_order"], crew["members"][1]["sort_order"] = 5, 0

    report = _refresh(path, _server_roster(H.fixture_doc(), 1, change))
    assert report.clean and not report.collisions
    ws = H.open_book(path)[H.CW_TAB]
    assert ws[f"{CW.ID}{H.cw_row(ws, 'MEMBER', 11)}"].value == 11
    assert ws[f"{CW.CODE}{H.cw_row(ws, 'MEMBER', 11)}"].value == "Laborer"
    assert _ops(path) == []


def test_checks_rows_alike_in_name_and_figure_follow_their_own_rows(tmp_path):
    import copy

    doc = H.fixture_doc()
    r2 = next(r for r in doc["resources"] if r["id"] == 2)
    r9 = next(r for r in doc["resources"] if r["id"] == 9)
    for k in ("name", "quantity", "unit_cost", "component_type", "labor_cost_basis",
              "burden_percentage", "includes_burden", "cost"):
        r9[k] = r2[k]
    path = H.build_book(doc, tmp_path / "e1.xlsx")
    assert _carpenters(path) == [1452, 1452]
    fresh = copy.deepcopy(doc)
    next(r for r in fresh["resources"] if r["id"] == 2).update(quantity="3.000", cost="2178.00",
                                                               v="2" * 16)
    assert _refresh(path, fresh).clean
    assert _carpenters(path) == [2178, 1452]
    # A Checks formula typed over: that row is left as it is, with a note.
    wb = H.open_book(path)
    ws = wb["Checks"]
    first = next(r for r in range(1, ws.max_row + 1) if ws[f"{CK.DESC}{r}"].value == "Carpenters")
    ws[f"{CK.EXCEL}{first}"] = 1
    H.save_book(wb, path)
    again = copy.deepcopy(fresh)
    next(r for r in again["resources"] if r["id"] == 9).update(quantity="4.000", cost="2904.00",
                                                               v="9" * 16)
    report = _refresh(path, again)
    assert report.clean
    assert _carpenters(path) == [2178, 2904]
    assert any(f"Checks row {first}" in n and "reads like another row" in n for n in report.notes)


# -- cached values (#370) -------------------------------------------------------------

def _cached(path, ref):
    from openpyxl import load_workbook

    return load_workbook(path, data_only=True)[H.CR_TAB][ref].value


def test_a_refreshed_book_carries_its_new_cached_totals(tmp_path):
    path = _book(tmp_path)
    ref = f"{CR.TOTAL}{_row(path, 'ACTIVITY', 1)}"
    built = _cached(path, ref)
    assert built is not None
    fresh = _fresh({1: {"quantity": "32.000"}})
    assert _refresh(path, fresh).clean
    rebuilt = H.build_book(fresh, tmp_path / "rebuilt.xlsx")
    want = _cached(rebuilt, f"{CR.TOTAL}{_row(rebuilt, 'ACTIVITY', 1)}")
    assert want != built
    assert _cached(path, ref) == pytest.approx(want)


def test_a_failed_caching_pass_leaves_a_refreshed_book_with_no_cached_values(tmp_path,
                                                                              monkeypatch):
    from openpyxl import load_workbook

    from estimating_tools.xlcalc import cache

    path = _book(tmp_path)
    ref = f"{CR.TOTAL}{_row(path, 'ACTIVITY', 1)}"
    assert _cached(path, ref) is not None

    def boom(_book):
        raise OSError("disk full")

    monkeypatch.setattr(cache, "evaluate", boom)
    assert _refresh(path, _fresh({1: {"quantity": "32.000"}})).clean
    wb = load_workbook(path, data_only=True)
    formulas = load_workbook(path)
    for ws in formulas.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    assert wb[ws.title][cell.coordinate].value is None, (ws.title,
                                                                         cell.coordinate)
    assert _ops(path) == []
