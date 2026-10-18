"""Cell <-> spec value comparisons: what counts as unchanged, and how a typed cell reads."""
from __future__ import annotations

from datetime import date, datetime

from estimating_tools.estimate_spec.readback.values import (
    as_text, fmt, read_number, same_number, same_text)


def test_a_text_field_is_unchanged_when_the_cell_holds_what_the_builder_wrote():
    assert same_text(2, "2")                       # the builder writes "2" as the number 2
    assert same_text("010", "010")                 # zero-padded stays text
    assert same_text(datetime(2026, 10, 1), "2026-10-01")
    assert same_text(None, "") and same_text("", None)
    assert not same_text("C-4", "C-3")
    assert not same_text(None, "C-3")


def test_a_number_field_is_unchanged_when_the_cell_holds_the_same_number_or_formula():
    assert same_number(8, 8) and same_number(8.0, 8)
    assert same_number("=640*1.1", "=640*1.1")
    assert not same_number(44.5, 42)
    assert not same_number(None, 42)
    assert same_number(None, None)


def test_a_placeholder_formula_is_unchanged_only_when_the_cell_matches_the_baseline():
    # A formula the spec carries as a placeholder (`={ref:...}`) is written
    # resolved by the builder; that resolved value -- the SAME cell read from
    # a fresh build of the unedited spec -- is what "unchanged" means, never
    # just "any formula is fine". review fix (Tasks 1-4): an estimator's
    # different formula typed over a placeholder input used to be silently
    # swallowed because any formula counted as unchanged.
    placeholder = "={ref:quantity.total}"
    assert same_number("=$B$8", placeholder, baseline="=$B$8")
    assert not same_number("=$B$8", placeholder)                 # no baseline given: never guess
    assert not same_number("=700", placeholder, baseline="=$B$8")
    assert not same_number("=B12*2", placeholder, baseline="=$B$8")


def test_reading_a_typed_number():
    assert read_number(44.5) == (44.5, None)
    assert read_number(42.0) == (42, None)
    assert read_number(" 1,200 ") == (1200, None)
    assert read_number("=640*1.1") == ("=640*1.1", None)
    assert read_number("=640*1.1", formula_ok=False)[1] == "holds the formula '=640*1.1' -- type a number"
    assert read_number("=B12*2")[1] == "holds the formula '=B12*2' -- type a number"
    assert read_number(None)[1] == "is blank"
    assert read_number("ten")[1] == "is 'ten', not a number"
    assert read_number(True)[1] == "is True, not a number"


def test_reading_a_typed_number_formats_a_date_through_as_text():
    # review fix (Tasks 1-4): a date cell's error used Python's raw repr.
    assert read_number(datetime(2026, 10, 1))[1] == "is '2026-10-01', not a number"
    assert read_number(date(2026, 10, 1))[1] == "is '2026-10-01', not a number"


def test_same_text_treats_an_excel_date_serial_as_its_iso_date():
    # review fix (Tasks 1-4): a bid-date cell that lost its date number
    # format still holds the same instant as a plain Excel serial number.
    assert same_text(46000, "2025-12-09")
    assert not same_text(46000, "2026-10-01")
    assert not same_text(46000, "C-3")                  # not a date-shaped `old`: no conversion


def test_text_and_report_formatting():
    assert as_text(date(2026, 10, 1)) == "2026-10-01"
    assert as_text(None) == ""
    assert [fmt(v) for v in (None, 1000, 44.5, 0.12, 42.0, "x")] == [
        "(blank)", "1,000", "44.5", "0.12", "42", "x"]


def test_excel_date_reads_a_serial_and_nothing_else():
    from datetime import datetime

    from estimating_tools.estimate_spec.readback.values import excel_date
    assert excel_date(46296) == datetime(2026, 10, 1)
    assert excel_date(10 ** 9) is None                  # out of range: not a date
    assert excel_date("46296") is None and excel_date(True) is None and excel_date(None) is None


def test_remap_rows_moves_same_sheet_references_and_nothing_else():
    from estimating_tools.estimate_spec.readback.values import remap_rows
    rows = {5: 5, 6: 6, 7: 8, 8: 9, 12: 13}
    assert remap_rows("=$B$8", rows) == "=$B$9"                       # anchors kept
    assert remap_rows("=B8*2+$C7", rows) == "=B9*2+$C8"
    assert remap_rows("=SUM(B6:B7)", rows) == "=SUM(B6:B8)"           # both endpoints
    # Another sheet's cells -- a quoted or bare qualifier, a whole range -- stay put.
    assert remap_rows("=VLOOKUP($A5,'Rates'!$A$5:$H$12,8,FALSE)", rows) == \
        "=VLOOKUP($A5,'Rates'!$A$5:$H$12,8,FALSE)"
    assert remap_rows("=Rates!B12*B8", rows) == "=Rates!B12*B9"
    assert remap_rows('=LOG10(B8)&"B8"', rows) == '=LOG10(B9)&"B8"'   # text is not a reference
    assert remap_rows("=$Q:$Q", rows) == "=$Q:$Q"
    assert remap_rows("=B3", rows) is None                           # that row is gone
    assert remap_rows(42, rows) == 42 and remap_rows("text", rows) == "text"
