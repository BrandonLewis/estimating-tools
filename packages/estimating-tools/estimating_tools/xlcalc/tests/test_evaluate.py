from __future__ import annotations

import datetime as dt

from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904, to_excel
from openpyxl.workbook.defined_name import DefinedName

from estimating_tools.xlcalc.book import Book
from estimating_tools.xlcalc.evaluate import Evaluator, Failed, evaluate
from estimating_tools.xlcalc.tests._calc import calc, results
from estimating_tools.xlcalc.values import Err


def test_cross_sheet_references_and_whole_columns():
    got = results({"A1": "=SUM(Rates!B:B)*2", "A2": "='Rates'!B2"},
                  {"Rates": {"B1": 1, "B2": 2, "B3": "=B1+B2"}})
    assert got["Sheet!A1"] == 12.0
    assert got["Sheet!A2"] == 2.0
    assert got["Rates!B3"] == 3.0


def test_defined_names_workbook_and_sheet_scope():
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws["A1"], ws["A2"], ws["B1"] = 4, "=Rate*2", "=Local+1"
    wb.defined_names["Rate"] = DefinedName("Rate", attr_text="Sheet!$A$1")
    ws.defined_names["Local"] = DefinedName("Local", attr_text="Sheet!$A$1")
    out = evaluate(Book.from_workbook(wb))
    assert out[("Sheet", 2, 1)] == 8.0
    assert out[("Sheet", 1, 2)] == 5.0


def test_a_long_chain_does_not_overflow_the_stack():
    cells = {"A1": 1}
    for r in range(2, 6001):
        cells[f"A{r}"] = f"=A{r - 1}+1"
    cells["B1"] = "=A6000"            # computed first: it pulls the whole chain
    got = results(cells)
    assert got["Sheet!B1"] == 6000.0


def test_a_running_max_over_the_rows_above_is_not_a_cycle():
    # HeavyBook's owner-row helper: each row reads every row above it. All
    # of them are needed at once by the last; none is an ancestor of another.
    cells = {"A4": 0}
    for r in range(5, 41):
        cells[f"B{r}"] = "ACTIVITY" if r % 7 == 0 else "STEP"
        cells[f"A{r}"] = f'=IF(B{r}="ACTIVITY",ROW(),MAX(A$4:A{r - 1}))'
    cells["C1"] = "=A40"                     # computed first: it needs the whole run
    got = results(cells)
    assert got["Sheet!C1"] == 35.0
    assert got["Sheet!A6"] == 0.0 and got["Sheet!A7"] == 7.0 and got["Sheet!A13"] == 7.0


def test_a_formula_reading_its_own_column_through_index():
    cells = {"A1": 5, "B1": 1, "B2": 1}
    cells["A2"] = "=INDEX(A:A,B2)"
    assert results(cells)["Sheet!A2"] == 5.0


def test_never_guess_unknown_circular_and_dependents():
    got = results({"A1": "=TODAY()", "A2": "=A1+1", "B1": "=B2", "B2": "=B1",
                   "C1": "=B1*2", "D1": "=IF(1,5,A1)", "E1": "={1,2}", "F1": "=E1"})
    assert got["Sheet!A1"] == Failed("unknown function TODAY")
    assert got["Sheet!A2"] == Failed("depends on an unevaluated cell")
    assert isinstance(got["Sheet!B1"], Failed) and isinstance(got["Sheet!B2"], Failed)
    assert "circular" in {got["Sheet!B1"].reason, got["Sheet!B2"].reason}
    assert isinstance(got["Sheet!C1"], Failed)
    assert got["Sheet!D1"] == 5.0                 # the untaken branch is not read
    assert got["Sheet!E1"] == Failed("parse error")
    assert got["Sheet!F1"] == Failed("depends on an unevaluated cell")


def test_a_range_of_many_cells_where_one_value_is_needed_is_not_guessed():
    assert calc("=A1:A3+1", A1=1) == Failed("a range where one value is needed")


def test_an_unknown_name_or_sheet_is_not_guessed():
    assert calc("=Nope*2") == Failed("unknown name NOPE")
    assert calc("=Gone!A1") == Failed("unknown sheet Gone")


def test_a_whole_column_reaches_the_last_row_of_the_sheet():
    # Not just the used rows: A100 is a valid blank cell, and every unused
    # row of the column is a blank COUNTIF sees.
    got = results({"A1": 5, "A2": "x", "B1": "=INDEX(A:A,100)", "B2": '=COUNTIF(A:A,"")',
                   "B3": '=COUNTIF(A:A,"<>x")', "B4": "=INDEX(A:A,1048577)",
                   "B5": '=SUMIF(Rates!A:A,"",Rates!B:B)'},
                  {"Rates": {"A1": "k", "B1": 1, "B2": 2, "B9": 4}})
    assert got["Sheet!B1"] == 0.0
    assert got["Sheet!B2"] == 1048576.0 - 2
    assert got["Sheet!B3"] == 1048576.0 - 1
    assert got["Sheet!B4"] == Err("#REF!")
    assert got["Sheet!B5"] == 6.0


def test_an_arithmetic_failure_fails_its_cell_and_no_other():
    got = results({"A1": "=ROUND(1,30)", "A2": "=A1+1", "A3": "=1+1"})
    assert got["Sheet!A1"] == Failed("arithmetic error (InvalidOperation)")
    assert got["Sheet!A2"] == Failed("depends on an unevaluated cell")
    assert got["Sheet!A3"] == 2.0


def test_growing_owner_row_ranges_keep_one_block_not_one_per_row():
    # HeavyBook's owner-row helper: each row reads every row above it.
    rows = 3000
    wb = Workbook()
    ws = wb.active
    for r in range(2, rows + 1):
        ws[f"A{r}"] = "ACTIVITY" if r % 10 == 2 else "LINE"
        ws[f"B{r}"] = f'=IF(A{r}="ACTIVITY",ROW(),MAX(B$1:B{r - 1}))'
    ev = Evaluator(Book.from_workbook(wb))
    out = ev.run()
    assert out[(ws.title, rows, 2)] == 2992.0
    # Retained cells: one list per column span, not rows**2 / 2 (4.5 million).
    assert sum(len(block) for block in ev._blocks.values()) <= rows


def test_dates_in_a_1904_book_keep_their_serial():
    wb = Workbook()
    wb.epoch = CALENDAR_MAC_1904
    ws = wb.active
    ws["A1"], ws["A2"] = dt.date(2026, 11, 5), "=A1+1"
    out = evaluate(Book.from_workbook(wb))
    assert out[(ws.title, 2, 1)] == to_excel(dt.date(2026, 11, 6), epoch=CALENDAR_MAC_1904)
