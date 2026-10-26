"""Payload text is never a live formula: only ``formulas.Formula`` values
are, so an item description ``=1+1`` or a resource named
``=HYPERLINK(...)`` stays the text the estimator typed into BidSheet.ai."""
from __future__ import annotations

from openpyxl import load_workbook

from estimating_tools.heavycivil import build, formulas, style

HOSTILE = {
    "description": "=1+1",
    "name": '=HYPERLINK("http://x","y")',
    "error": "#N/A",
}

#: Formula cells per sheet in the fixture book -- every one a builder's.
FORMULA_CELLS = {"Bid Form": 31, "Recap": 63, "Cost Report": 234, "Crews": 13, "Rates": 0,
                 "Schedule": 4, "Checks": 165, "Flat": 42, "_shares": 56, "_cal": 0, "_wb": 0}


def _build(doc):
    return build.build(doc, style=style.load_style(), exported_at="2026-10-20T09:00:00Z",
                       host="www.bidsheet.ai")


def _cells_with(book, value):
    return [c for ws in book.worksheets for c in ws._cells.values() if c.value == value]


def _hostile_doc(doc):
    doc["items"][0]["description"] = HOSTILE["description"]
    doc["resources"][0]["name"] = HOSTILE["name"]
    doc["activities"][0]["warnings"] = [HOSTILE["error"]]
    doc["activities"][1]["name"] = HOSTILE["error"]
    return doc


def test_payload_text_starting_with_equals_is_text(doc, tmp_path):
    book = _build(_hostile_doc(doc))
    for value in HOSTILE.values():
        cells = _cells_with(book, value)
        assert cells, value
        assert all(c.data_type == "s" for c in cells), value
    path = tmp_path / "hostile.xlsx"
    build.save(book, path)
    reloaded = load_workbook(path)
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


def test_builders_return_formula_markers():
    assert isinstance(formulas.row_total(5), formulas.Formula)
    assert isinstance(formulas.crew_sum("A", None), formulas.Formula)
    assert isinstance(formulas.item_breakdown_split("B", 5, "_shares", 2, 1), formulas.Formula)
