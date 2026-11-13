"""Payload text is never a live formula: only the template's formulas are,
so an item description ``=1+1`` or a resource named ``=HYPERLINK(...)``
stays the text the estimator typed into BidSheet.ai."""
from __future__ import annotations

from openpyxl import load_workbook

from estimating_tools.heavybook.tests import _readback as H

HOSTILE = {
    "description": "=1+1",
    "name": '=HYPERLINK("http://x","y")',
    "error": "#N/A",
}

#: Formula cells per sheet in the fixture book -- every one the template's
#: (a prototype row's formulas, placed), or the engine's owner-row helper
#: (the Cost Report's ``AJ``, the Crews' ``R``) on every filled row and
#: prototype. A change of the template moves these; re-count them from a
#: fresh build.
FORMULA_CELLS = {"Bid Form": 63, "Recap": 74, "Cost Report": 403, "Crews": 38, "Rates": 0,
                 "Schedule": 267, "Checks": 347, "Flat": 65, "Allocation": 72,
                 "Bid Coverage": 6, "_cal": 0, "_wb": 0, "_templates": 326}


def _build(doc, tmp_path):
    return load_workbook(H.build_book(doc, tmp_path / "hostile.xlsx"))


def _cells_with(book, value):
    return [c for ws in book.worksheets for c in ws._cells.values() if c.value == value]


def _hostile_doc(doc):
    doc["items"][0]["description"] = HOSTILE["description"]
    doc["resources"][0]["name"] = HOSTILE["name"]
    doc["activities"][0]["warnings"] = [HOSTILE["error"]]
    doc["activities"][1]["name"] = HOSTILE["error"]
    return doc


def test_payload_text_starting_with_equals_is_text(doc, tmp_path):
    reloaded = _build(_hostile_doc(doc), tmp_path)
    for value in HOSTILE.values():
        cells = _cells_with(reloaded, value)
        assert cells, value
        assert all(c.data_type == "s" for c in cells), value


def test_every_formula_cell_is_a_builder_formula(book):
    counts = {ws.title: sum(1 for c in ws._cells.values() if c.data_type == "f")
              for ws in book.worksheets}
    assert counts == FORMULA_CELLS
    # The fixture's payload text has no leading "=": every "=" cell is live.
    for ws in book.worksheets:
        for c in ws._cells.values():
            if isinstance(c.value, str) and c.value.startswith("="):
                assert c.data_type == "f", (ws.title, c.coordinate, c.value)
