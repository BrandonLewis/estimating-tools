"""Coded inputs normalised to BidSheet.ai's spelling, numbers and clears, as
ops (spec §2 Case and codes; §3 Clears)."""
from __future__ import annotations

import pytest

from estimating_tools.heavycivil.tests import _readback as H
from estimating_tools.heavycivil.columns import CR
from estimating_tools.heavycivil.readback import ReadRefused


@pytest.fixture
def path(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")


def _edit(path, cells, sheet=H.CR_TAB):
    wb = H.open_book(path)
    ws = wb[sheet]
    for addr, value in cells(ws).items():
        ws[addr] = value
    H.save_book(wb, path)


def _problems(path):
    with pytest.raises(ReadRefused) as exc:
        H.read(path)
    return exc.value.problems


def test_a_lower_case_unit_is_normalised(path):
    _edit(path, lambda ws: {f"{CR.UNIT}{H.cr_row(ws, 'STEP', 1)}": "hours"})
    cs = H.read(path)
    assert cs.ops == [{"op": "step.update", "ref": 1, "v": "128bba9d35b48338",
                       "fields": {"duration_unit": "HOURS"}}]


def test_a_lower_case_code_equal_to_the_baseline_is_no_change(path):
    _edit(path, lambda ws: {f"{CR.TYPE}{H.cr_row(ws, 'RESOURCE', 1)}": "EQUIPMENT",
                            f"{CR.BINC}{H.cr_row(ws, 'RESOURCE', 1)}": "n"})
    assert H.read(path).ops == []


def test_an_unknown_code_is_refused(path):
    _edit(path, lambda ws: {f"{CR.TYPE}{H.cr_row(ws, 'RESOURCE', 2)}": "labour"})
    problems = _problems(path)
    assert any(p.column == CR.TYPE and "'labour' is not one of" in p.message
               for p in problems)


def test_a_non_number_is_refused(path):
    _edit(path, lambda ws: {f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}": "lots"})
    assert any(p.column == CR.QTY and "'lots' is not a number" in p.message
               for p in _problems(path))


def test_a_number_typed_as_text_is_accepted(path):
    _edit(path, lambda ws: {f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}": " 31 "})
    cs = H.read(path)
    assert cs.ops[0]["op"] == "resource.update" and cs.ops[0]["fields"] == {"quantity": "31"}


def test_a_formula_typed_into_an_input_is_refused(path):
    _edit(path, lambda ws: {f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}": "=2*15"})
    assert any("holds a formula" in p.message for p in _problems(path))


def test_a_clear_the_server_cannot_take_is_refused(path):
    _edit(path, lambda ws: {f"{CR.UCOST}{H.cr_row(ws, 'RESOURCE', 1)}": None})
    assert any("Unit cost can't be cleared" in p.message for p in _problems(path))


def test_a_clear_the_server_takes_is_sent_as_null(path):
    _edit(path, lambda ws: {f"G{H.find_row(ws, 'ITEM_BID', 3, kind_col='J', id_col='K')}": None},
          sheet=H.BF_TAB)
    cs = H.read(path)
    assert cs.ops == [{"op": "item.update", "ref": 3, "v": "7940f1306f4b1b78",
                       "fields": {"bid_unit_price_override": None}}]


@pytest.mark.parametrize("sheet, cell", [
    (H.CR_TAB, lambda ws: f"{CR.PROD}{H.cr_row(ws, 'ACTIVITY', 2)}"),
    (H.CR_TAB, lambda ws: f"{CR.QTY}{H.cr_row(ws, 'STEP', 1)}"),
    (H.CW_TAB, lambda ws: f"C{H.cw_row(ws, 'MEMBER', 1)}"),
    (H.BF_TAB, lambda ws: f"G{H.find_row(ws, 'ITEM_BID', 3, kind_col='J', id_col='K')}"),
], ids=["activity-production", "step-duration", "member-count", "bid-override"])
def test_an_unreadable_cell_on_an_existing_row_refuses_the_read(path, sheet, cell):
    """``fields.diff`` skips an unreadable field; the read must still refuse
    rather than send the row's other edits without it."""
    _edit(path, lambda ws: {cell(ws): "abc"}, sheet=sheet)
    assert any("'abc' is not a number" in p.message for p in _problems(path))


def test_an_unreadable_cell_on_a_copied_row_refuses_the_read(path):
    def copy(ws):
        r = H.cr_row(ws, "RESOURCE", 1)
        new = H.insert_copies(ws, r, r, H.block_end(ws, 1))
        return {f"{CR.UCOST}{new}": "abc"}
    _edit(path, copy)
    assert any("'abc' is not a number" in p.message for p in _problems(path))


def test_an_unreadable_estimate_input_is_reported_once(path):
    _edit(path, lambda ws: {"C4": "abc"}, sheet=H.BF_TAB)
    problems = [p for p in _problems(path) if p.row == 4]
    assert len(problems) == 1 and "'abc' is not a number" in problems[0].message
