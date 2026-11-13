"""A prototype row's formula copied into place (``refs.place``), and what a
formula reads (``refs.references``, ``refs.functions``) for the template
lint."""
from __future__ import annotations

import pytest
from openpyxl.formula.translate import Translator

from estimating_tools.exchange import refs


@pytest.mark.parametrize("body, want", [
    ("C17*E17", "C40*E40"),                                     # its own row
    ("IF(W17=\"ACTIVITY\",ROW(),MAX(AJ$4:AJ16))", "IF(W40=\"ACTIVITY\",ROW(),MAX(AJ$4:AJ39))"),
    ("INDEX($X:$X,MAX($AJ17,1))", "INDEX($X:$X,MAX($AJ40,1))"),  # whole columns stay
    ("\"C17\"&C17", "\"C17\"&C40"),                             # text is not a reference
    ("SUMIF('_shares'!$B:$B,$X17,'_shares'!E:E)", "SUMIF('_shares'!$B:$B,$X40,'_shares'!E:E)"),
    ("Rates!B17+Rates!$B$3", "Rates!B40+Rates!$B$3"),           # Excel's copy, qualified too
    ("hc.total*2", "hc.total*2"),
    ("'[1]Other'!A17", "'[1]Other'!A40"),
])
def test_a_row_moves_as_excels_copy_moves_it(body, want):
    assert refs.place(body, origin=17, dest=40) == want
    # The same as openpyxl's translator for a copy down the same column.
    assert refs.place(body, origin=17, dest=40) == Translator(
        "=" + body, origin="C17").translate_formula("C40")[1:]


def test_an_owner_row_reads_its_own_placed_brackets():
    # Prototype: ACTIVITY at 7, START 8, sample RESOURCE 9, END 10; placed at
    # 20 (ACTIVITY), 21 (START), 22..25 (four resources), 26 (END).
    block = {7: 20, 8: 21, 10: 26}
    assert refs.place("SUM(M8:M10)*AA7", origin=7, dest=20, block=block) == "SUM(M21:M26)*AA20"
    assert refs.place('SUMIF(S8:S10,"labor",C8:C10)', origin=7, dest=20, block=block) == \
        'SUMIF(S21:S26,"labor",C21:C26)'
    # A row outside the block moves by the offset (the row above).
    assert refs.place("MAX(AJ$4:AJ6)", origin=7, dest=20, block=block) == "MAX(AJ$4:AJ19)"


def test_a_qualified_reference_is_not_read_as_a_block_row():
    assert refs.place("Other!M8", origin=7, dest=20, block={8: 21}) == "Other!M21"


def test_a_row_pushed_off_the_sheet_is_refused():
    with pytest.raises(refs.RefsError, match="off the sheet"):
        refs.place("A3", origin=5, dest=1)


def test_references_name_their_sheet_shape_and_rows():
    found = refs.references("SUM(A1:INDEX(B:B,3))+'X y'!C$4+hc.name+Table1[C]+5:6+A2:A4")
    assert [(r.text, r.sheet, r.shape, r.rows) for r in found] == [
        ("A1", None, "cell", ((1, False),)),
        ("B:B", None, "columns", ()),
        ("'X y'!C$4", "X y", "cell", ((4, True),)),
        ("hc.name", None, "name", ()),
        ("Table1[C]", None, "name", ()),
        ("5:6", None, "rows", ((5, False), (6, False))),
        ("A2:A4", None, "area", ((2, False), (4, False))),
    ]
    assert refs.references("'[1]Book'!A1")[0].external
    assert refs.references("Jan:Mar!A1")[0].three_d


def test_functions_are_named_upper_case():
    assert refs.functions('SUM(A1:INDEX(B:B,3))+indirect("A1")+OFFSET(A1,1,1)') == {
        "SUM", "INDEX", "INDIRECT", "OFFSET"}
    with pytest.raises(refs.RefsError):
        refs.functions("A1#")
