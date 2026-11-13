"""A book the code writers built (pack version 1, ``fixtures/v1-book.xlsx``)
still reads, applies (patches) and refreshes under the version-2 pack: its
stamped declaration and its own prototypes drive the engine, and its Checks
figures refresh through ``heavybook.legacy_checks``."""
from __future__ import annotations

import shutil
from pathlib import Path

from estimating_tools.exchange.facts import read_facts
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CK, CR
from estimating_tools.heavybook.tests import _readback as H
from estimating_tools.heavybook.tests.test_patch import _server

V1 = Path(__file__).parent / "fixtures" / "v1-book.xlsx"


def _copy(tmp_path):
    out = tmp_path / "v1.xlsx"
    shutil.copy(V1, out)
    return out


def test_it_is_detected_and_reads_clean(tmp_path):
    book = _copy(tmp_path)
    facts = read_facts(book)
    assert facts.properties["estimate_format"] == "heavybook 1"
    assert hb_pack.pack().detect(facts) == "ok"
    assert hb_pack.pack().read(book).change_set.ops == []


def test_an_edit_is_applied_and_patched_from_its_own_prototypes(tmp_path):
    pack, book = hb_pack.pack(), _copy(tmp_path)
    wb = H.open_book(book)
    H.type_row(wb[H.CR_TAB], H.block_end(wb[H.CR_TAB], 2),
               {CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"})
    H.save_book(wb, book)
    first = pack.read(book)
    assert [op["op"] for op in first.change_set.ops] == ["resource.create"]
    fresh, plan = _server(H.fixture_doc(), first.change_set)
    assert pack.patch(book, first.change_set, plan, fresh).baseline_replaced
    assert pack.read(book).change_set.ops == []


def test_a_server_change_refreshes_and_its_checks_figure_follows(tmp_path):
    pack, book = hb_pack.pack(), _copy(tmp_path)
    fresh = H.fixture_doc()
    for res in fresh["resources"]:
        if res["id"] == 2:
            res.update(cost="999.00", quantity="3.000", v="a" * 16)
    report = pack.refresh(book, fresh)
    assert report.clean and report.baseline_replaced
    ws = H.open_book(book)["Checks"]
    assert any(ws[f"{CK.KIND}{r}"].value == "resource" and ws[f"{CK.BIDSHEET}{r}"].value == 999
               for r in range(5, ws.max_row + 1))


def test_lines_bidsheet_added_are_noted_as_checks_figures_with_no_row(tmp_path):
    """A refresh never adds Checks rows to a version-1 book: the figures
    ``legacy_checks`` lists for lines BidSheet.ai added are a note."""
    from estimating_tools.exchange.tests.test_refresh_scenarios import _added

    book = _copy(tmp_path)
    fresh = _added(_added(H.fixture_doc(), 5, 10, "Gravel"), 1, 12, "Water")
    report = hb_pack.pack().refresh(book, fresh)
    assert report.clean and report.rows_added == 2
    assert "Checks: 2 figure(s) BidSheet.ai has now have no row; a rebuild adds them" \
        in report.notes


def test_a_checks_row_that_reads_like_another_keeps_its_figure(tmp_path):
    """Two of BidSheet.ai's lines now read alike (resource 9 renamed
    "Carpenters", as resource 2 is): the book's Carpenters row whose formula
    was typed over cannot tell which figure is its own, so it keeps the
    build's, with a note."""
    from openpyxl import load_workbook

    book = _copy(tmp_path)
    wb = load_workbook(book)
    ws = wb["Checks"]
    row = next(r for r in range(5, ws.max_row + 1) if ws[f"{CK.DESC}{r}"].value == "Carpenters")
    before = ws[f"{CK.BIDSHEET}{row}"].value
    ws[f"{CK.EXCEL}{row}"] = 1
    wb.save(book)
    fresh = H.fixture_doc()
    next(r for r in fresh["resources"] if r["id"] == 9).update(name="Carpenters", v="9" * 16)
    report = hb_pack.pack().refresh(book, fresh)
    assert report.clean
    assert any(f"Checks row {row}" in n and "reads like another row" in n for n in report.notes)
    assert load_workbook(book)["Checks"][f"{CK.BIDSHEET}{row}"].value == before
