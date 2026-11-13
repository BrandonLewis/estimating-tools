"""#439: a declaration that shows only part of the read model. A HeavyBook
book whose stamped declaration drops sheets reads clean (nothing of the
missing sheets is read, so nothing of theirs is deleted), reads its own
sheets' edits, and refreshes; a ``fixed`` block refuses what an estimator
adds to it."""
from __future__ import annotations

import json

import pytest

from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange import writer
from estimating_tools.exchange.reader import ReadRefused, read_book
from estimating_tools.exchange.reader.classify import NO_ADD
from estimating_tools.heavybook.columns import CR, CW
from estimating_tools.heavybook.tests import _readback as H


def _restamp(path, change):
    """Rewrite the book's stamped declaration with ``change(declaration)``."""
    wb = H.open_book(path)
    raw = json.loads(wb[exchange_stamp.SHEET][exchange_stamp.CELL].value)
    wb.close()
    change(raw["declaration"])
    writer.write(path, {exchange_stamp.SHEET: {exchange_stamp.CELL: exchange_stamp.dumps(raw)}})
    return path


def _without(*keys, prototypes=()):
    def change(decl):
        for key in keys:
            del decl["sheets"][key]
        for key in prototypes:
            del decl["prototypes"][key]
        decl["navigator"] = {}
    return change


def _cost_report_only(tmp_path, name="book.xlsx"):
    path = H.build_book(H.fixture_doc(), tmp_path / name)
    return _restamp(path, _without("crews", "bid_form", "rates", prototypes=("member",)))


def _crews_only(tmp_path, name="book.xlsx"):
    path = H.build_book(H.fixture_doc(), tmp_path / name)
    return _restamp(path, _without("cost_report", "bid_form", "rates",
                                   prototypes=("activity", "stepped", "resource", "step")))


def test_a_cost_report_only_declaration_reads_clean(tmp_path):
    assert read_book(_cost_report_only(tmp_path)).ops == []


def test_a_crews_only_declaration_reads_clean_and_deletes_no_activity(tmp_path):
    assert read_book(_crews_only(tmp_path)).ops == []


def test_a_cost_report_only_book_reads_its_own_edits(tmp_path):
    path = _cost_report_only(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = 40
    wb[H.CW_TAB][f"{CW.COUNT}{H.cw_row(wb[H.CW_TAB], 'MEMBER', 1)}"] = 9   # not declared: unread
    H.save_book(wb, path)
    (op,) = read_book(path).ops
    assert (op["op"], op["ref"], op["fields"]) == ("resource.update", 1, {"quantity": "40"})


def test_a_cost_report_only_book_refreshes(tmp_path):
    from estimating_tools.exchange.refresh import refresh
    from estimating_tools.heavybook import pack as hb_pack

    path = _cost_report_only(tmp_path)
    fresh = H.fixture_doc()
    for res in fresh["resources"]:
        if res["id"] == 1:
            res.update(quantity="32.000", v="0000000000000001")
    report = refresh(path, fresh, pack=hb_pack.pack())
    assert report.clean and report.baseline_replaced
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 32


def test_a_crews_only_book_refreshes_past_what_it_does_not_show(tmp_path):
    """No sheet shows activities, items or element quantities: a structural
    change to one (an activity's first step, an added activity) is nothing
    this book holds, so it neither refuses the refresh nor is reported."""
    from estimating_tools.exchange.refresh import refresh
    from estimating_tools.heavybook import pack as hb_pack

    path = _crews_only(tmp_path)
    fresh = H.fixture_doc()
    acts = {a["id"]: a for a in fresh["activities"]}
    acts[5]["steps"] = [dict(acts[4]["steps"][0], id=50, name="Server step", v="5" * 16)]
    fresh["activities"].append(dict(acts[8], id=60, name="Server activity", v="6" * 16))
    report = refresh(path, fresh, pack=hb_pack.pack())
    assert report.clean and report.structural == [] and report.baseline_replaced
    assert read_book(path).ops == []


@pytest.mark.parametrize("block, edit", [
    ("resources", lambda ws: H.type_row(ws, H.block_end(ws, 2), {
        CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"})),
    ("steps", lambda ws: H.type_row(ws, H.cr_row(ws, "START", parent=4), {
        CR.DESC: "Strip", CR.QTY: 1})),
])
def test_a_row_added_to_a_fixed_block_refuses_the_read(tmp_path, block, edit):
    path = H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")

    def fixed(decl):
        decl["sheets"]["cost_report"]["blocks"][block]["fixed"] = True
    _restamp(path, fixed)
    assert read_book(path).ops == []
    wb = H.open_book(path)
    row = edit(wb[H.CR_TAB])
    H.save_book(wb, path)
    with pytest.raises(ReadRefused) as exc:
        read_book(path)
    assert [(p.row, p.message) for p in exc.value.problems] == [(row, NO_ADD)]
