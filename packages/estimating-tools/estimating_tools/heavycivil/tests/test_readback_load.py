"""Loading: the layout check and the embedded baseline (spec §1, §2 Load)."""
from __future__ import annotations

import json

import pytest
from openpyxl import Workbook

from estimating_tools.heavycivil import baseline as hc_baseline
from estimating_tools.heavycivil.readback import ReadRefused, baseline
from estimating_tools.heavycivil.tests import _readback as H


@pytest.fixture
def path(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")


def _refused(path):
    with pytest.raises(ReadRefused) as exc:
        baseline.load(path)
    return str(exc.value)


def test_load_decodes_the_baseline(path):
    book = baseline.load(path)
    assert book.doc == H.fixture_doc()
    assert book.model.estimate.id == 1 and book.tab("cost_report") == "Cost Report"
    assert book.kinds["cost_report"]["kinds"]["STEPS"] == {"activity_id": "Z"}


def test_layout_1_book_is_refused(path):
    wb = H.open_book(path)
    meta = json.loads(wb["_wb"]["A1"].value)
    meta["layout_version"] = 1
    wb["_wb"]["A1"] = json.dumps(meta)
    H.save_book(wb, path)
    message = _refused(path)
    assert "layout 1" in message and "rebuild the book" in message


def test_tampered_baseline_is_refused(path):
    wb = H.open_book(path)
    chunk = wb["_wb"]["B1"].value
    wb["_wb"]["B1"] = ("A" if chunk[10] != "A" else "B").join((chunk[:10], chunk[11:]))
    H.save_book(wb, path)
    message = _refused(path)
    assert "baseline" in message and "rebuild the book" in message


def test_missing_chunk_is_refused(path):
    wb = H.open_book(path)
    wb["_wb"]["B1"] = None
    H.save_book(wb, path)
    message = _refused(path)
    assert "chunk count: found 0, the layout says 1" in message and "rebuild the book" in message


def test_a_book_without_a_baseline_is_refused(path):
    wb = H.open_book(path)
    meta = json.loads(wb["_wb"]["A1"].value)
    del meta["baseline"]
    wb["_wb"]["A1"] = json.dumps(meta)
    H.save_book(wb, path)
    assert "no baseline" in _refused(path)


def test_not_a_heavycivil_book(tmp_path):
    other = tmp_path / "other.xlsx"
    Workbook().save(other)
    assert "not a HeavyCivil workbook" in _refused(other)


def test_no_such_file(tmp_path):
    assert "no such file" in _refused(tmp_path / "missing.xlsx")


def _edit_meta(edit):
    def apply(wb, tmp_path):
        meta = json.loads(wb["_wb"]["A1"].value)
        edit(meta)
        wb["_wb"]["A1"] = json.dumps(meta)
    return apply


def _set_a1(value):
    def apply(wb, tmp_path):
        wb["_wb"]["A1"] = value
    return apply


def _rename_rates(wb, tmp_path):
    wb["Rates"].title = "My Rates"


def _numeric_chunk(wb, tmp_path):
    wb["_wb"]["B1"] = 12345


def _invalid_payload(wb, tmp_path):
    """A baseline that decodes and matches its checksum, but is not a payload
    ``model.parse`` accepts."""
    doc = H.fixture_doc()
    del doc["estimate"]
    chunks, meta = hc_baseline.encode(doc)
    layout_doc = json.loads(wb["_wb"]["A1"].value)
    layout_doc["baseline"] = meta
    wb["_wb"]["A1"] = json.dumps(layout_doc)
    for k, chunk in enumerate(chunks, 1):
        wb["_wb"][f"B{k}"] = chunk


def _set(key, value):
    def edit(meta):
        meta[key] = value
    return edit


def _drop_kinds(sheet):
    def edit(meta):
        meta["row_kinds"] = [k for k in meta["row_kinds"] if k["sheet"] != sheet]
    return edit


@pytest.mark.parametrize("damage, expected", [
    (_rename_rates, ("the rates tab ('Rates') is missing or was renamed -- rename it back, "
                     "or rebuild the book from BidSheet.ai")),
    (_set_a1("{not json"), "the layout in _wb!A1 is unreadable"),
    (_set_a1(None), "the layout in _wb!A1 is unreadable"),
    (_edit_meta(_set("format", "other")), "not a HeavyCivil workbook"),
    (_edit_meta(_set("layout_version", "2")), "an unrecognised layout version"),
    (_edit_meta(_set("tabs", ["Cost Report"])), "the layout in _wb!A1 is unreadable"),
    (_edit_meta(_set("row_kinds", {"kind": "ITEM"})), "the layout in _wb!A1 is unreadable"),
    (_edit_meta(_set("row_kinds", [{"sheet": "cost_report"}])),
     "the layout in _wb!A1 is unreadable"),
    (_edit_meta(_set("row_kinds", ["ITEM"])), "the layout in _wb!A1 is unreadable"),
    (_edit_meta(_drop_kinds("crews")), "the layout in _wb!A1 is unreadable"),
    (_numeric_chunk, "chunk 1 (_wb!B1) is not text"),
    (_invalid_payload, "the embedded baseline is not valid"),
], ids=["renamed-tab", "bad-json-a1", "empty-a1", "format", "version-type", "tabs-list",
        "row-kinds-dict", "row-kinds-missing-key", "row-kinds-str", "row-kinds-no-crews",
        "numeric-chunk",
        "payload-error"])
def test_damaged_book_is_refused(path, tmp_path, damage, expected):
    wb = H.open_book(path)
    damage(wb, tmp_path)
    H.save_book(wb, path)
    message = _refused(path)
    assert expected in message


@pytest.mark.parametrize("content", [b"not a zip at all", b"PK\x03\x04 truncated"],
                         ids=["not-xlsx", "corrupt-zip"])
def test_unreadable_file_is_refused(tmp_path, content):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(content)
    assert "cannot read" in _refused(bad)
