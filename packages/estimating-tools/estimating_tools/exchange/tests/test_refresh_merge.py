"""The refresh's row-by-row decision (``exchange.refresh.merge.plan``), on
HeavyBook books, before anything is written."""
from __future__ import annotations

from estimating_tools.exchange import model
from estimating_tools.exchange.refresh import merge
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import BF, CR, CW
from estimating_tools.heavybook.tests import _readback as H


def _plan(path, fresh):
    from estimating_tools.exchange.reader import run

    book, scanned, changes, change_set, problems = run(path, pack=hb_pack.pack())
    try:
        assert not problems.items
        return merge.plan(book, scanned, changes, change_set, model.parse(fresh))
    finally:
        book.wb.close()


def _book(tmp_path, edit=None):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    if edit is not None:
        wb = H.open_book(path)
        edit(wb)
        H.save_book(wb, path)
    return path


def _row(path, kind, ident, tab=H.CR_TAB):
    ws = H.open_book(path)[tab]
    return H.cr_row(ws, kind, ident) if tab == H.CR_TAB else H.cw_row(ws, kind, ident)


def _resource(doc, ident, **fields):
    res = next(r for r in doc["resources"] if r["id"] == ident)
    res.update(fields)
    return doc


def test_a_server_only_change_is_a_write_of_the_input_and_the_v(tmp_path):
    path = _book(tmp_path)
    m = _plan(path, _resource(H.fixture_doc(), 1, quantity="32.000", v="1" * 16))
    row = _row(path, "RESOURCE", 1)
    assert m.clean and not m.inserts and not m.deletes
    assert m.cells["cost_report"] == {(row, CR.QTY): 32, (row, CR.V): "1" * 16}


def test_a_both_sides_change_is_a_collision_with_three_values(tmp_path):
    def edit(wb):
        ws = wb[H.CR_TAB]
        ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = 31
    path = _book(tmp_path, edit)
    m = _plan(path, _resource(H.fixture_doc(), 1, quantity="32.000", v="1" * 16))
    (c,) = m.collisions
    assert (c.sheet, c.row) == (H.CR_TAB, _row(path, "RESOURCE", 1))
    assert c.message == "line 'CAT 336' Quantity: BidSheet.ai 32, this book 31 (built with 30)"


def test_the_same_change_on_both_sides_is_convergent(tmp_path):
    def edit(wb):
        ws = wb[H.CR_TAB]
        ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = 32
    path = _book(tmp_path, edit)
    m = _plan(path, _resource(H.fixture_doc(), 1, quantity="32.000", v="1" * 16))
    assert m.clean and m.convergent == {("RESOURCE", 1)}
    assert (_row(path, "RESOURCE", 1), CR.QTY) not in m.cells.get("cost_report", {})


def test_an_estimate_input_changed_on_the_server_goes_to_its_named_row(tmp_path):
    path = _book(tmp_path)
    doc = H.fixture_doc()
    doc["estimate"].update(markup_percentage="12.50", v="e" * 16)
    m = _plan(path, doc)
    cells = m.cells["bid_form"]
    assert 12.5 in cells.values() and "e" * 16 in cells.values()
    assert all(letter in (BF.VALUE, "L") for (_row, letter) in cells)


def test_an_added_resource_is_an_insert_above_its_activitys_end(tmp_path):
    path = _book(tmp_path)
    doc = H.fixture_doc()
    res = dict(next(r for r in doc["resources"] if r["id"] == 2), id=10, name="Gravel",
               sort_order=5, v="a" * 16)
    doc["resources"].append(res)
    m = _plan(path, doc)
    (ins,) = m.inserts
    assert (ins.key, ins.kind, ins.owner) == ("cost_report", "RESOURCE", 2)
    assert ins.before == H.cr_row(H.open_book(path)[H.CR_TAB], "END", parent=2)
    assert [r.id for r in ins.rows] == [10]


def test_a_deleted_member_is_a_row_delete_and_its_replacement_an_insert(tmp_path):
    path = _book(tmp_path)
    doc = H.fixture_doc()
    crew = next(c for c in doc["crews"] if c["id"] == 1)
    crew["members"][0]["id"] = 11
    crew["v"] = "c" * 16
    m = _plan(path, doc)
    assert m.deletes == [("crews", _row(path, "MEMBER", 1, H.CW_TAB))]
    (ins,) = m.inserts
    assert (ins.key, ins.kind, [x.id for x in ins.rows]) == ("crews", "MEMBER", [11])
    assert ins.before == H.cw_row(H.open_book(path)[H.CW_TAB], "CREW_END", parent=1)


def test_a_crew_export_value_is_written(tmp_path):
    path = _book(tmp_path)
    doc = H.fixture_doc()
    crew = next(c for c in doc["crews"] if c["id"] == 1)
    crew.update(hours_per_shift="9.00", v="c" * 16)
    m = _plan(path, doc)
    row = _row(path, "CREW", 1, H.CW_TAB)
    assert m.cells["crews"][(row, CW.HPS)] == 9 and m.cells["crews"][(row, CW.V)] == "c" * 16


def test_structural_changes_are_named(tmp_path):
    path = _book(tmp_path)
    doc = H.fixture_doc()
    next(a for a in doc["activities"] if a["id"] == 2)["parent_id"] = 1
    doc["crews"] = [c for c in doc["crews"] if c["id"] != 2]
    for a in doc["activities"]:
        if a.get("crew_id") == 2:
            a["crew_id"] = None
    m = _plan(path, doc)
    text = " ".join(m.structural)
    assert "activity 'Walls': its parent_id changed" in text
    assert "crew Pour crew was deleted" in text
    assert all(s.endswith("rebuild it from BidSheet.ai") for s in m.structural)


def test_signatures_ignore_v_and_keys_name_the_row():
    op = {"op": "element.set_quantity", "ref": 1, "v": "x",
          "fields": {"key": "concrete_cy", "override_value": "5"}}
    assert merge.op_key(op) == ("ELEMENT_QTY", (1, "concrete_cy"))
    assert merge.signature(op) == merge.signature(dict(op, v="y"))
    assert merge.op_key({"op": "resource.create", "ref": "new:r1", "fields": {}}) is None
