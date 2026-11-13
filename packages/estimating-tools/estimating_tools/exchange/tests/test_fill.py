"""Template fill end to end (engine spec, Fill; "Testing": round trip,
determinism, package): the test pack filled from HeavyBook's fixture
payload reads back with no changes, carries its stamp, baseline, names and
properties, writes the same bytes twice, keeps a chart and grows the ranges
over its rows, and refuses -- writing nothing -- what it cannot fill."""
from __future__ import annotations

import copy
import json
import zipfile

import pytest
from openpyxl import load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment

from estimating_tools.exchange import baseline, writer
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.template import TemplatePack
from estimating_tools.exchange.tests import _template as T
from estimating_tools.exchange.types import BuildRefused
from estimating_tools.heavybook.tests import _readback as H

AT = "2026-11-06T09:00:00Z"


def _pack(tmp_path, **kw):
    return TemplatePack(T.make(tmp_path / "pack", **kw))


def _build(pack, out, doc=None, **options):
    return pack.build(doc or H.fixture_doc(), out, options={"exported_at": AT, **options})


def test_a_filled_book_reads_back_with_no_changes(tmp_path):
    pack = _pack(tmp_path)
    report = _build(pack, tmp_path / "book.xlsx")
    assert report.path == tmp_path / "book.xlsx" and report.exported_at == AT
    result = pack.read(tmp_path / "book.xlsx")
    assert result.problems == [] and result.change_set.ops == []


def test_the_book_prices_live_and_carries_cached_values(tmp_path):
    pack = _pack(tmp_path)
    _build(pack, tmp_path / "book.xlsx")
    ws = load_workbook(tmp_path / "book.xlsx", data_only=True)[T.TAB]
    totals = {ws[f"{T.KIND}{r}"].value + str(ws[f"{T.ID}{r}"].value): ws[f"F{r}"].value
              for r in range(T.FIRST, ws.max_row + 1)
              if ws[f"{T.KIND}{r}"].value in ("ITEM", "ACTIVITY")}
    # Item 1: its activities 1..5 (Ties, 3 x 2 counts, under Walls); 5's cost is its own.
    assert totals["ITEM1"] == pytest.approx(5550 + 2200 + 60 + 420 + 1000.01)
    assert totals["ACTIVITY3"] == pytest.approx(10 * 6)
    assert ws["A1"].value == "E" and ws["A2"].value == AT


def test_the_filled_books_prototypes_carry_the_owner_row_helper(tmp_path):
    """The template's prototypes leave the helper blank (the lint allows it);
    the filled book's carry it on every blocks-sheet prototype row, for the
    rows a patch or refresh inserts from them (Task 14 prices one)."""
    pack = _pack(tmp_path)
    _build(pack, tmp_path / "book.xlsx")
    ws = load_workbook(tmp_path / "book.xlsx")[T.PROTO]
    share = next(r for r in range(1, ws.max_row + 1) if ws[f"F{r}"].value == "SHARE")
    assert [ws[f"{T.OWNER}{r}"].value for r in range(T.FIRST, share - 1)] == [
        T._owner_row(r) for r in range(T.FIRST, share - 1)]
    assert ws[f"{T.OWNER}{share}"].value is None                # a display prototype: none
    template = load_workbook(tmp_path / "pack" / "template.xlsx")[T.PROTO]
    assert template[f"{T.OWNER}{T.FIRST}"].value is None        # the template is untouched


def test_the_stamp_baseline_names_and_properties(tmp_path):
    pack = _pack(tmp_path)
    doc = H.fixture_doc()
    _build(pack, tmp_path / "book.xlsx", doc, host="https://Example.test/x")
    wb = load_workbook(tmp_path / "book.xlsx")
    st = exchange_stamp.parse(json.loads(wb["_wb"]["A1"].value))
    assert (st.pack, st.host, st.exported_at, st.page) == (
        {"name": "mini-book", "version": "1"}, "example.test", AT, False)
    assert st.declaration == T.DECLARATION
    chunks = exchange_stamp.chunks_of(wb["_wb"])
    assert baseline.decode(chunks, st.baseline) == doc
    assert wb.defined_names[exchange_stamp.NAME].attr_text == "'_wb'!$A$1"
    assert {p.name: p.value for p in wb.custom_doc_props.props} == {
        "estimate_format": "mini-book 1", "estimate_id": "1", "bidsheet_host": "example.test",
        "exported_at": AT}


def test_two_fills_write_the_same_bytes_and_differ_only_in_the_export_time(tmp_path):
    pack = _pack(tmp_path)
    a, b, c = (tmp_path / f"{n}.xlsx" for n in "abc")
    _build(pack, a)
    _build(pack, b)
    pack.build(H.fixture_doc(), c, options={"exported_at": "2026-11-07T09:00:00Z"})
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(c) as zc:
        differ = {n for n in za.namelist() if za.read(n) != zc.read(n)}
        parts = writer._sheet_parts(za)
    assert differ == {parts["_wb"], parts[T.TAB], "docProps/custom.xml"}   # A2 names the time


def test_the_template_keeps_a_chart_and_its_ranges_grow_with_the_rows(tmp_path):
    def edit(wb):
        ws = wb[T.TAB]
        chart = BarChart()
        chart.add_data(Reference(ws, min_col=6, min_row=T.HEADER, max_row=T.FIRST))
        ws.add_chart(chart, "S2")
        ws["R1"] = f"=SUM(F{T.HEADER}:F{T.FIRST})"
    pack = _pack(tmp_path, edit=edit)
    _build(pack, tmp_path / "book.xlsx")
    last = T.FIRST + 42
    with zipfile.ZipFile(tmp_path / "book.xlsx") as z:
        chart = z.read("xl/charts/chart1.xml")
    assert f"'{T.TAB}'!$F${T.HEADER}:$F${last}".encode() in chart
    assert load_workbook(tmp_path / "book.xlsx")[T.TAB]["R1"].value == \
        f"=SUM(F{T.HEADER}:F{last})"


def test_what_a_prototype_row_holds_and_the_fill_drops_needs_allow_dropped(tmp_path):
    def edit(wb):
        wb[T.PROTO]["B17"].comment = Comment("a hint", "author")
    pack = _pack(tmp_path, edit=edit)
    with pytest.raises(BuildRefused, match="a note on a prototype row -- the fill does not copy "
                                           "it onto the rows it places; pass --allow-dropped"):
        _build(pack, tmp_path / "book.xlsx")
    assert not (tmp_path / "book.xlsx").exists()
    report = _build(pack, tmp_path / "book.xlsx", allow_dropped=True)
    assert report.dropped == [f"{T.PROTO}!B17: a note on a prototype row"]


def test_a_payload_or_template_the_fill_refuses_writes_nothing(tmp_path):
    pack = _pack(tmp_path)
    template = (tmp_path / "pack" / "template.xlsx").read_bytes()
    doc = H.fixture_doc()
    del doc["estimate"]
    with pytest.raises(BuildRefused) as exc:
        _build(pack, tmp_path / "book.xlsx", doc)
    assert exc.value.kind == "payload"
    broken = _pack(tmp_path / "broken", edit=lambda wb: wb[T.PROTO].__setitem__("C17", 2))
    with pytest.raises(BuildRefused) as exc:
        _build(broken, tmp_path / "book.xlsx")
    assert exc.value.kind == "template" and "C is the quantity input" in str(exc.value)
    assert not (tmp_path / "book.xlsx").exists()
    assert (tmp_path / "pack" / "template.xlsx").read_bytes() == template
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]     # no temp left


def test_a_fill_that_would_not_read_back_clean_is_refused(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["estimate"]["formulas"]["RESOURCE"] = ["F", "D"]   # D holds no formula
    pack = _pack(tmp_path, declaration=doc)
    with pytest.raises(BuildRefused, match="the filled book does not read back clean"):
        _build(pack, tmp_path / "book.xlsx")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pack"]


def test_an_output_that_is_the_template_itself_is_refused(tmp_path):
    """``--template DIR -o DIR/template.xlsx`` would replace the template with
    the filled book."""
    pack = _pack(tmp_path)
    template = tmp_path / "pack" / "template.xlsx"
    before = template.read_bytes()
    for out in (template, tmp_path / "pack" / ".." / "pack" / "template.xlsx"):
        with pytest.raises(BuildRefused, match="is the template itself") as exc:
            _build(pack, out)
        assert exc.value.kind == "template"
    assert template.read_bytes() == before
    assert sorted(p.name for p in (tmp_path / "pack").iterdir()) == ["pack.yaml", "template.xlsx"]
