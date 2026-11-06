"""Excel's reference shifting for whole-row inserts and deletes, one formula
at a time (``exchange.refs``), and parity with the test suite's Excel
simulator on every formula of a real HeavyBook book."""
from __future__ import annotations

import re

import pytest

from estimating_tools.exchange import refs

CR = "Cost Report"


@pytest.mark.parametrize("body, own, want", [
    ("A9", True, "A9"),
    ("A10", True, "A12"),
    ("$A$10", True, "$A$12"),
    ("SUM(C8:C10)", True, "SUM(C8:C12)"),            # spans the point: grows
    ("SUM(C10:C11)", True, "SUM(C12:C13)"),
    ("MAX(AJ$4:AJ9)", True, "MAX(AJ$4:AJ9)"),
    ("INDEX($X:$X,MAX($AJ10,1))", True, "INDEX($X:$X,MAX($AJ12,1))"),
    ('"A10"&A10', True, '"A10"&A12'),                # a string literal is not a reference
    ("SUM($9:$14)", True, "SUM($9:$16)"),
    ("SUM(A10:INDEX(B:B,3))", True, "SUM(A12:INDEX(B:B,3))"),
    ("SUM(INDEX(B:B,3):A10)", True, "SUM(INDEX(B:B,3):A12)"),
    ("hc.bid_totals", True, "hc.bid_totals"),
    ("SUM(Table1[Col])", True, "SUM(Table1[Col])"),
    ("A10", False, "A10"),                           # another sheet's own reference
    ("'Cost Report'!$R$12", False, "'Cost Report'!$R$14"),
    ("'cost report'!R12", False, "'cost report'!R14"),   # sheet names ignore case
    ("Rates!$A$12", False, "Rates!$A$12"),
    ("'[1]Cost Report'!A10", False, "'[1]Cost Report'!A10"),   # another workbook
])
def test_insert(body, own, want):
    assert refs.insert(body, sheet=CR, own=own, at=10, count=2) == want


def test_a_quoted_apostrophe_sheet_name_matches():
    assert refs.insert("'It''s'!A10", sheet="It's", own=False, at=10, count=1) == "'It''s'!A11"


@pytest.mark.parametrize("body, own, want, lost", [
    ("A9", True, "A9", False),
    ("A10", True, "#REF!", True),
    ("A12", True, "A10", False),
    ("SUM(C8:C12)", True, "SUM(C8:C10)", False),
    ("SUM(C10:C11)", True, "SUM(#REF!)", True),
    ("SUM(C10:C13)", True, "SUM(C10:C11)", False),
    ("SUM(C5:C10)", True, "SUM(C5:C9)", False),
    ("'Cost Report'!$A$11", False, "'Cost Report'!#REF!", True),
    ("#REF!+A12", True, "#REF!+A10", False),          # an old #REF! is not a new loss
])
def test_delete(body, own, want, lost):
    assert refs.delete(body, sheet=CR, own=own, first=10, count=2) == (want, lost)


def test_a_3d_reference_and_an_unreadable_formula_are_refused():
    with pytest.raises(refs.RefsError, match="3-D"):
        refs.insert("SUM(Sheet1:Sheet3!A1)", sheet=CR, own=True, at=1, count=1)
    with pytest.raises(refs.RefsError, match="cannot read"):
        refs.insert("A1#", sheet=CR, own=True, at=1, count=1)


def test_mentions_finds_a_qualified_reference_only():
    assert refs.mentions("'Cost Report'!A1*2", CR)
    assert not refs.mentions("A1*2", CR)
    assert not refs.mentions('"Cost Report"&A1', CR)


def test_ranges_and_spans():
    assert refs.sqref_insert("A5:A10 C12 F4:F11", 10, 2) == "A5:A12 C14 F4:F13"
    assert refs.sqref_delete("A5:A10 C10:C11 D12", 10, 2) == "A5:A9 D10"
    assert refs.sqref_delete("C10:C11", 10, 2) == ""
    assert refs.span("B2:C9") == (2, 9) and refs.span("$A$4") == (4, 4)
    assert refs.span("A:A") is None


def _normalise(text):
    """The simulator drops a qualified ``#REF!``'s sheet; Excel keeps it."""
    return re.sub(r"(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!#REF!", "#REF!", text)


def test_parity_with_the_excel_simulator_on_every_heavybook_formula(tmp_path):
    from estimating_tools.estimate_spec.tests._fieldbook import (_delete_sheet_refs,
                                                                 _shift_sheet_refs)
    from estimating_tools.heavybook.tests import _readback as H

    path = H.build_book(H.fixture_doc(), tmp_path / "b.xlsx")
    wb = H.open_book(path)
    seen = 0
    for ws in wb.worksheets:
        own = ws.title == CR
        for row in ws.iter_rows():
            for cell in row:
                f = cell.value
                if not (isinstance(f, str) and f.startswith("=")):
                    continue
                seen += 1
                assert "=" + refs.insert(f[1:], sheet=CR, own=own, at=12, count=1) == \
                    _shift_sheet_refs(f, CR, own, 12, 1), (ws.title, cell.coordinate)
                text, _lost = refs.delete(f[1:], sheet=CR, own=own, first=13, count=1)
                assert _normalise("=" + text) == _delete_sheet_refs(f, CR, own, 13), \
                    (ws.title, cell.coordinate)
    assert seen > 300


def test_lowercase_columns_are_references_too():
    # Excel reads column letters in any case (PR #444 review).
    assert refs.insert("SUM(a10:a12)", sheet=CR, own=True, at=10, count=2) == "SUM(a12:a14)"
    assert refs.insert("SUM(a10:INDEX(b:b,3))", sheet=CR, own=True, at=10, count=2) == \
        "SUM(a12:INDEX(b:b,3))"
    assert refs.delete("a10*2", sheet=CR, own=True, first=10, count=1) == ("#REF!*2", True)
    assert refs.span("b2:c9") == (2, 9)


def test_a_quoted_3d_span_is_refused():
    with pytest.raises(refs.RefsError, match="3-D"):
        refs.insert("SUM('Sheet 1:Sheet 3'!A10)", sheet=CR, own=False, at=10, count=1)


def test_a_3d_span_that_does_not_name_the_sheet_still_reaches_the_refusal():
    # Start:End reads every sheet between them, the edited one perhaps among them.
    assert refs.could_mention("SUM(Start:End!A10)", CR)
    assert refs.could_mention("SUM('Start one:End'!A10)", CR)
    assert refs.mentions("SUM(Start:End!A10)", CR)
    assert not refs.could_mention("SUM(A1:A3)+Rates!A1", CR)


#: Excel's own results for a row inserted above row 5, and row 5 deleted, on
#: a formula in row 1 of the edited sheet (Excel 365, PR #444 review).
EXCEL_ROW5 = [
    ("SUM(A2:A1048576)", "SUM(A2:A1048576)", "SUM(A2:A1048576)"),
    ("A1048576", "#REF!", "A1048575"),
    ("SUM(A6:A1048576)", "SUM(A7:A1048576)", "SUM(A5:A1048576)"),
    ("A5:A5:A7", "A6:A6:A8", "#REF!:A6"),
    ("SUM((A5,A8))", "SUM((A6,A9))", "SUM((#REF!,A7))"),
    ("SUM(A4:A5)", "SUM(A4:A6)", "SUM(A4:A4)"),
    ("A$5+$A5+$A$5", "A$6+$A6+$A$6", "#REF!+#REF!+#REF!"),
    ("SUM(4:6)", "SUM(4:7)", "SUM(4:5)"),
    ("SUM(5:5)", "SUM(6:6)", "SUM(#REF!)"),
]


@pytest.mark.parametrize("body, inserted, deleted", EXCEL_ROW5)
def test_what_excel_writes_for_row_5(body, inserted, deleted):
    assert refs.insert(body, sheet=CR, own=True, at=5, count=1) == inserted
    assert refs.delete(body, sheet=CR, own=True, first=5, count=1)[0] == deleted


def test_a_range_list_to_the_last_row_does_not_block_an_insert():
    assert refs.sqref_insert("A2:A1048576 B1048576", 5, 1) == "A2:A1048576"
    assert refs.sqref_delete("A6:A1048576", 5, 1) == "A5:A1048576"


def test_a_name_past_the_last_column_is_not_a_reference():
    assert refs.insert("XYZ1+XFD1+xfe9", sheet=CR, own=True, at=1, count=1) == "XYZ1+XFD2+xfe9"


def test_spaces_and_line_breaks_survive_and_an_unmoved_formula_is_untouched():
    body = "IF(A1>0,\r\n  B12,\n C12)"
    assert refs.insert(body, sheet=CR, own=True, at=10, count=1) == "IF(A1>0,\r\n  B13,\n C13)"
    assert refs.insert("SUM( A1 ,  B2 )", sheet=CR, own=True, at=10, count=1) == "SUM( A1 ,  B2 )"
    assert refs.insert("SUM( A11 ,  B2 )", sheet=CR, own=True, at=10, count=1) == \
        "SUM( A12 ,  B2 )"


SHEETS = ("Jan", "Feb", "Mar", CR)


def test_a_3d_span_is_refused_only_when_it_reads_the_edited_sheet():
    with pytest.raises(refs.RefsError, match="3-D"):
        refs.insert("SUM(Jan:Mar!A5)", sheet="Feb", own=False, at=1, count=1, sheets=SHEETS)
    with pytest.raises(refs.RefsError, match="3-D"):
        refs.insert("SUM('Jan:Cost Report'!A5)", sheet=CR, own=False, at=1, count=1,
                    sheets=SHEETS)
    assert refs.insert("SUM('Cost Report'!A5,Jan:Mar!B2)", sheet=CR, own=True, at=1, count=1,
                       sheets=SHEETS) == "SUM('Cost Report'!A6,Jan:Mar!B2)"
