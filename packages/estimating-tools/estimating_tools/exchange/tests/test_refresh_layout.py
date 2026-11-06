"""A refresh's decision as writer input (``exchange.refresh.layout``): row
ops bottom-up per sheet, every cell where its row ends up."""
from __future__ import annotations

from estimating_tools.exchange import model, rowops
from estimating_tools.exchange.refresh import layout, merge
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CR
from estimating_tools.heavybook.tests import _readback as H


def test_ops_run_bottom_up_and_cells_follow_their_rows(tmp_path):
    from estimating_tools.exchange.reader import run

    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    doc = H.fixture_doc()
    doc["resources"] = [r for r in doc["resources"] if r["id"] != 1]          # activity 1
    res = dict(next(r for r in doc["resources"] if r["id"] == 2), id=10, name="Gravel",
               sort_order=5, v="a" * 16)
    doc["resources"].append(res)                                               # activity 2
    next(r for r in doc["resources"] if r["id"] == 8).update(quantity="2.000", v="8" * 16)
    book, scanned, changes, change_set, _problems = run(path, pack=hb_pack.pack())
    try:
        m = merge.plan(book, scanned, changes, change_set, model.parse(doc))
        ops, cells = layout.layout(book, m)
        ws = book.ws("cost_report")
        cat, end2 = H.cr_row(ws, "RESOURCE", 1), H.cr_row(ws, "END", parent=2)
        fence = H.cr_row(ws, "RESOURCE", 8)
    finally:
        book.wb.close()
    assert [type(op).__name__ for op in ops] == ["InsertRows", "DeleteRows"]
    assert ops[0].before == end2 and ops[1].first == cat and end2 > cat
    assert ops[0].skip == (CR.ID, CR.V)                      # stored tags; the parent is derived
    sheet = cells[H.CR_TAB]
    # The new row: above activity 2's END, one row up once CAT 336 is gone.
    assert sheet[f"{CR.ID}{end2 - 1}"] == 10 and sheet[f"{CR.DESC}{end2 - 1}"] == "Gravel"
    # Resource 8 sits below both ops: up one, down one.
    assert sheet[f"{CR.QTY}{fence}"] == 2


def test_remap_refuses_a_cell_on_a_deleted_row():
    rowmap = rowops.RowMap([rowops.DeleteRows("S", 5)])
    assert layout.remap({"S": {"A4": 1, "B9": 2}}, rowmap) == {"S": {"A4": 1, "B8": 2}}
    try:
        layout.remap({"S": {"A5": 1}}, rowmap)
    except ValueError as exc:
        assert "S!A5" in str(exc)
    else:
        raise AssertionError("a cell on a deleted row must be refused")
