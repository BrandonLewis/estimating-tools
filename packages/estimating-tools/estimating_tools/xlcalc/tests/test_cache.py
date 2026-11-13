from __future__ import annotations

import io
import time

from openpyxl import Workbook, load_workbook

from estimating_tools import xlcalc
from estimating_tools.xlcalc import cache


def _save(tmp_path, cells, name="b.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    for ref, v in cells.items():
        ws[ref] = v
    path = tmp_path / name
    wb.save(path)
    return path


def test_values_land_where_data_only_readers_see_them(tmp_path):
    # The #370 case: L x H / 27 read as 0 CY because nothing was cached.
    path = _save(tmp_path, {"A1": 81, "B1": 90, "C1": "=ROUND(A1*B1/27,0)", "D1": '=C1&" CY"'})
    before = load_workbook(path, data_only=True)["Sheet"]
    assert before["C1"].value is None
    report = xlcalc.cache_values(path)
    ws = load_workbook(path, data_only=True)["Sheet"]
    assert (ws["C1"].value, ws["D1"].value) == (270, "270 CY")
    assert (report.formulas, report.cached, report.reasons) == (2, 2, {})
    assert report.summary() is None


def test_uncached_cells_are_counted_and_named(tmp_path):
    path = _save(tmp_path, {"A1": "=TODAY()", "A2": "=A1+1", "A3": "=1+1"})
    out = io.StringIO()
    report = xlcalc.cache_or_warn(path, stream=out)
    assert report.summary() == ("cached 1 of 3 formulas; 2 not evaluated "
                                "(depends on an unevaluated cell: 1, unknown function TODAY: 1)")
    assert out.getvalue() == f"b.xlsx: {report.summary()}\n"
    ws = load_workbook(path, data_only=True)["Sheet"]
    assert (ws["A1"].value, ws["A2"].value, ws["A3"].value) == (None, None, 2)


def test_a_hidden_sheets_uncached_cell_is_not_reported(tmp_path):
    # A template book's prototype rows (hidden ``_templates``) read their own
    # blank id tags: left uncached, never reported -- nothing the estimator
    # sees holds them. A visible cell that reads one is reported.
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws["A1"] = "=1+1"
    tpl = wb.create_sheet("_templates")
    tpl.sheet_state = "hidden"
    tpl["A1"] = "=SUMIF(B:B,C1,D:D)"                # C1 blank: a blank criterion
    path = tmp_path / "h.xlsx"
    wb.save(path)
    out = io.StringIO()
    report = xlcalc.cache_or_warn(path, stream=out)
    assert (report.formulas, report.cached, report.hidden) == (2, 1, 1)
    assert report.summary() is None and out.getvalue() == ""
    ws["A2"] = "=_templates!A1"
    wb.save(path)
    assert xlcalc.cache_or_warn(path, stream=io.StringIO()).summary() == (
        "cached 1 of 2 formulas; 1 not evaluated (depends on an unevaluated cell: 1)")


def test_a_fully_cached_book_prints_nothing(tmp_path):
    out = io.StringIO()
    xlcalc.cache_or_warn(_save(tmp_path, {"A1": "=1+1"}), stream=out)
    assert out.getvalue() == ""


def test_a_failure_never_raises_and_removes_values_that_may_be_stale(tmp_path, monkeypatch):
    # A patched book may carry values Excel computed before the patch.
    path = _save(tmp_path, {"A1": 2, "B1": "=A1*2"})
    xlcalc.cache_values(path)
    assert load_workbook(path, data_only=True)["Sheet"]["B1"].value == 4

    def boom(_book):
        raise OSError("disk full")

    monkeypatch.setattr(cache, "evaluate", boom)
    out = io.StringIO()
    assert xlcalc.cache_or_warn(path, stream=out) is None
    assert "warning: b.xlsx: formula values not cached (OSError: disk full)" in out.getvalue()
    ws = load_workbook(path)["Sheet"]
    assert (ws["A1"].value, ws["B1"].value) == (2, "=A1*2")
    assert load_workbook(path, data_only=True)["Sheet"]["B1"].value is None


def test_a_failure_to_remove_the_values_is_named_and_never_raises(tmp_path, monkeypatch):
    path = _save(tmp_path, {"A1": "=1+1"})
    before = path.read_bytes()

    def boom(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(cache, "cache_values", boom)
    monkeypatch.setattr(cache.writer, "write_cached", boom)
    out = io.StringIO()
    assert xlcalc.cache_or_warn(path, stream=out) is None
    assert "old formula values could not be removed either (OSError: disk full)" in out.getvalue()
    assert path.read_bytes() == before


def test_ten_thousand_formulas_in_under_two_seconds(tmp_path):
    cells = {}
    for r in range(1, 2001):
        cells[f"A{r}"] = r
        cells[f"B{r}"] = f"=A{r}*2"
        cells[f"C{r}"] = f"=B{r}+A{r}"
        cells[f"D{r}"] = f"=IF(C{r}>100,ROUND(C{r}/3,2),0)"
        cells[f"E{r}"] = f"=INDEX($B:$B,{r})"
        cells[f"F{r}"] = f"=SUM($B{r}:$E{r})"
    path = _save(tmp_path, cells)
    started = time.perf_counter()
    report = xlcalc.cache_values(path)
    took = time.perf_counter() - started
    assert report.cached == report.formulas == 10000
    assert took < 2.0, f"{took:.2f}s"
