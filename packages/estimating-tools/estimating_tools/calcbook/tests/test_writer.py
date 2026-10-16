"""Tests for calcbook workbook/styling helpers (#202)."""
from __future__ import annotations

import pytest

openpyxl = pytest.importorskip("openpyxl")

from estimating_tools.calcbook import writer as w   # noqa: E402


def test_new_workbook_creates_named_sheets():
    wb = w.new_workbook("BASIS", "RATES")
    assert wb.sheetnames == ["BASIS", "RATES"]


def test_save_is_byte_deterministic(tmp_path):
    def build(path):
        wb = w.new_workbook("S")
        w.header(wb["S"], ["a", "b", "c"])
        wb["S"].append([1, 2, 3])
        w.save(wb, str(path))

    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    build(a)
    build(b)
    assert a.read_bytes() == b.read_bytes()


def test_header_is_bold_filled_and_frozen():
    wb = w.new_workbook("S")
    ws = wb["S"]
    w.header(ws, ["pile", "hours"])
    assert [c.value for c in ws[1]] == ["pile", "hours"]
    assert ws["A1"].font.bold is True
    assert ws.freeze_panes == "A2"


def test_kv_marks_input_cells_yellow_and_returns_refs():
    wb = w.new_workbook("BASIS")
    ws = wb["BASIS"]
    refs = w.kv(ws, [
        ("job", "JOB-1", "spec"),
        ("productive factor", 0.75, "the most-abused number"),
    ], start_row=1, inputs=["productive factor"])
    # values landed in column B, notes in C
    assert ws["A2"].value == "productive factor"
    assert ws["B2"].value == 0.75
    assert ws["C1"].value == "spec"
    # the input value cell is yellow; the non-input one is not
    assert ws["B2"].fill.fgColor.rgb.endswith("FFFF00")
    assert ws["B1"].fill.patternType in (None, "none")
    # refs point back at the value cells
    assert refs["productive factor"] == "B2"
    assert refs["job"] == "B1"


def test_mark_input_applies_yellow():
    wb = w.new_workbook("S")
    ws = wb["S"]
    ws["A1"] = 5
    w.mark_input(ws["A1"])
    assert ws["A1"].fill.fgColor.rgb.endswith("FFFF00")


def test_rate_table_builds_override_columns(tmp_path):
    wb = w.new_workbook("RATES")
    ws = wb["RATES"]
    # shipped rate columns C,D,E; a single override in F drives effective G,H,I
    refs = w.rate_table(
        ws,
        headers=["class", "name", "low", "likely", "high", "override",
                 "eff_low", "eff_likely", "eff_high"],
        rows=[["1", "Sand", 10, 12, 14], ["2", "Clay", 6, 8, 10]],
        shipped_cols=["C", "D", "E"],
        override_col="F",
        effective_cols=["G", "H", "I"],
    )
    # row 2 effective_low formula: IF(F2="",C2,F2)
    assert ws["G2"].value == '=IF($F2="",C2,$F2)'
    assert ws["I3"].value == '=IF($F3="",E3,$F3)'
    # the override column is an input (yellow)
    assert ws["F2"].fill.fgColor.rgb.endswith("FFFF00")
    # refs expose the effective cells for downstream formulas
    assert refs["eff_likely"][0] == "RATES!$H$2"


def test_set_widths():
    wb = w.new_workbook("S")
    ws = wb["S"]
    w.set_widths(ws, {"A": 20, "B": 8})
    assert ws.column_dimensions["A"].width == 20


def test_section_merges_across_span():
    wb = w.new_workbook("S")
    ws = wb["S"]
    w.section(ws, "RATE BASIS", row=1, span=3)
    assert ws["A1"].value == "RATE BASIS"
    assert ws["A1"].font.bold is True
    assert "A1:C1" in [str(rng) for rng in ws.merged_cells.ranges]


def test_lazy_writer_names_resolve_through_package():
    import estimating_tools.calcbook as cb
    assert cb.INPUT_FILL is w.INPUT_FILL          # via package __getattr__
    assert cb.new_workbook is w.new_workbook
