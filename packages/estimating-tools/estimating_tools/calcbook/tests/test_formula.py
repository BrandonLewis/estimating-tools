"""Tests for calcbook formula helpers (#202)."""
from __future__ import annotations

from estimating_tools.calcbook import formula as f


def test_cell_ref_absolute_and_relative():
    assert f.cell_ref("RATES", "B", 4) == "RATES!$B$4"
    assert f.cell_ref(None, "B", 4) == "$B$4"
    assert f.cell_ref(None, "B", 4, abs_col=False, abs_row=False) == "B4"
    assert f.cell_ref("TIME", 3, 7) == "TIME!$C$7"       # numeric column


def test_cell_ref_quotes_sheet_names_with_spaces_or_apostrophes():
    assert f.cell_ref("Rate Basis", "G", 2) == "'Rate Basis'!$G$2"
    assert f.cell_ref("O'Brien", "A", 1) == "'O''Brien'!$A$1"
    assert f.cell_ref("# 1 - MOB", "B", 3) == "'# 1 - MOB'!$B$3"


def test_pert_formula():
    assert f.pert("D2", "E2", "F2") == "=(D2+4*E2+F2)/6"
    assert (f.pert("RATES!$H$2", "RATES!$I$2", "RATES!$J$2")
            == "=(RATES!$H$2+4*RATES!$I$2+RATES!$J$2)/6")


def test_override_formula():
    # effective = the shipped value unless an override was typed in
    assert f.override("D2", "$G$2") == '=IF($G$2="",D2,$G$2)'
