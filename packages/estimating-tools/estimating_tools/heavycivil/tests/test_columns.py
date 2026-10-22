from __future__ import annotations

from estimating_tools.heavycivil import columns as C


def test_letters_are_unique_per_sheet():
    for sheet, cols in C.SHEETS.items():
        letters = [c.letter for c in cols]
        assert len(letters) == len(set(letters)), sheet


def test_hidden_columns_are_never_optional():
    for cols in C.SHEETS.values():
        assert not [c for c in cols if c.hidden and c.optional]


def test_cost_report_constants_match_the_tuple():
    by_key = {c.key: c.letter for c in C.COST_REPORT}
    assert by_key["total"] == C.CR.TOTAL == "R"
    assert by_key["kind"] == C.CR.KIND == "W"


def test_sheets_follow_the_tab_order():
    assert list(C.SHEETS) == ["bid_form", "recap", "cost_report", "crews", "rates",
                              "schedule", "checks", "flat"]


def test_bid_form_input_rows_sit_above_the_header_and_are_unique():
    rows = list(C.BF.ROWS.values())
    assert all(r < C.BF.HEADER_ROW for r in rows)
    assert len(rows) == len(set(rows))
    assert C.BF.FIRST_ROW == C.BF.HEADER_ROW + 1
