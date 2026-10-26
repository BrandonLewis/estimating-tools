"""The Rates sheet is read-only (spec §2 The Rates sheet)."""
from __future__ import annotations

import pytest

from estimating_tools.heavycivil.tests import _readback as H
from estimating_tools.heavycivil.readback import ReadRefused

READ_ONLY = "library rates are read-only: set the member's Rate override on the Crews sheet"


@pytest.fixture
def path(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")


def _two_labor_rates_doc():
    doc = H.fixture_doc()
    doc["rates"]["labor"].append({"id": 2, "classification": "LABORER", "unit": "HR",
                                  "rate": "40.10"})
    return doc


def _rate_row(ws, rate_id):
    return next(r for r in range(1, ws.max_row + 1) if ws[f"A{r}"].value == rate_id)


def _problems(path, fn):
    wb = H.open_book(path)
    fn(wb[H.RT_TAB])
    H.save_book(wb, path)
    with pytest.raises(ReadRefused) as exc:
        H.read(path)
    return exc.value.problems


def test_a_changed_rate_is_refused(path):
    problems = _problems(path, lambda ws: ws.__setitem__(f"D{_rate_row(ws, 1)}", 60))
    assert [(p.sheet, p.message.endswith(READ_ONLY + " instead")) for p in problems] == [
        (H.RT_TAB, True), (H.RT_TAB, True)]   # the changed row, and rate 1 now missing


def test_an_added_rate_row_is_refused(path):
    def add(ws):
        r = _rate_row(ws, 1) + 1
        H.type_row(ws, r, {"A": 2, "B": "LABORER", "C": "HR", "D": 40})
    problems = _problems(path, add)
    assert len(problems) == 1 and READ_ONLY in problems[0].message
    assert problems[0].row is not None


def test_a_deleted_rate_row_is_refused(path):
    problems = _problems(path, lambda ws: ws.delete_rows(_rate_row(ws, 1)))
    assert len(problems) == 1 and "labor rate 1 (OPER) was deleted" in problems[0].message


def test_an_unedited_rates_sheet_reads_clean(path):
    assert H.read(path).ops == []


# Beyond the plan: reordering refuses; Excel's float noise, stray spaces,
# blank-vs-empty text and text numbers do not.

def test_reordered_rate_rows_are_refused(tmp_path):
    path = H.build_book(_two_labor_rates_doc(), tmp_path / "book.xlsx")

    def swap(ws):
        a, b = _rate_row(ws, 1), _rate_row(ws, 2)
        H.cut_rows(ws, b, b, a)
    problems = _problems(path, swap)
    assert len(problems) == 1 and "reordered" in problems[0].message
    assert READ_ONLY in problems[0].message and problems[0].row is not None


def test_a_changed_name_or_unit_is_refused(path):
    problems = _problems(path, lambda ws: ws.__setitem__(f"C{_rate_row(ws, 1)}", "DAY"))
    assert len(problems) == 2 and all(READ_ONLY in p.message for p in problems)


def test_noise_that_is_not_an_edit_reads_clean(tmp_path):
    path = H.build_book(_two_labor_rates_doc(), tmp_path / "book.xlsx")
    wb = H.open_book(path)
    ws = wb[H.RT_TAB]
    r1, r2 = _rate_row(ws, 1), _rate_row(ws, 2)
    ws[f"A{r1}"] = 1.0                 # an id Excel hands back as a float
    ws[f"B{r1}"] = " OPER "            # stray spaces
    ws[f"D{r1}"] = "$54.00"            # a text number
    ws[f"D{r2}"] = 40.1 + 1e-14        # float noise
    H.save_book(wb, path)
    assert H.read(path).ops == []


# A book with three rates in each section (material ones carry ``cost``).

def _three_by_three_doc():
    doc = H.fixture_doc()
    doc["rates"] = {
        "labor": [{"id": 1, "classification": "OPER", "unit": "HR", "rate": "54.00"},
                  {"id": 2, "classification": "LABORER", "unit": "HR", "rate": "40.10"},
                  {"id": 3, "classification": "FOREMAN", "unit": "HR", "rate": "62.25"}],
        "equipment": [{"id": 11, "name": "CAT 336", "unit": "HR", "rate": "185.00"},
                      {"id": 12, "name": "D6 DOZER", "unit": "HR", "rate": "150.00"},
                      {"id": 13, "name": "WATER TRUCK", "unit": "HR", "rate": "95.50"}],
        "material": [{"id": 21, "description": "CLASS 2 BASE", "unit": "TON", "cost": "28.00"},
                     {"id": 22, "description": "PCC", "unit": "CY", "cost": "165.00"},
                     {"id": 23, "description": "REBAR", "unit": "LB", "cost": "0.95"}],
    }
    return doc


@pytest.fixture
def big(tmp_path):
    return H.build_book(_three_by_three_doc(), tmp_path / "big.xlsx")


def _title_row(ws, title):
    return next(r for r in range(1, ws.max_row + 1) if ws[f"A{r}"].value == title)


def test_an_unedited_multi_section_sheet_reads_clean(big):
    assert H.read(big).ops == []


def test_a_changed_material_cost_is_refused(big):
    problems = _problems(big, lambda ws: ws.__setitem__(f"D{_rate_row(ws, 22)}", 170))
    assert len(problems) == 2 and all(READ_ONLY in p.message for p in problems)
    assert any("material rate 22 (PCC) was deleted" in p.message for p in problems)


def test_a_renamed_section_title_is_refused_once(big):
    problems = _problems(
        big, lambda ws: ws.__setitem__(f"A{_title_row(ws, 'Material costs')}", "Materials"))
    assert len(problems) == 1
    assert "the material section title was changed or deleted" in problems[0].message
    assert READ_ONLY in problems[0].message


def test_a_heading_row_overwritten_with_a_rate_is_refused(big):
    def overwrite(ws):
        r = _title_row(ws, "Labor rates") + 1
        for letter, value in {"A": 4, "B": "SURVEYOR", "C": "HR", "D": 70}.items():
            ws[f"{letter}{r}"] = value
    problems = _problems(big, overwrite)
    assert len(problems) == 1 and "changed or added" in problems[0].message


def test_a_repeated_title_with_a_row_under_it_is_refused(big):
    def repeat(ws):
        r = _title_row(ws, "Material costs")
        H.type_row(ws, r, {"A": "Labor rates"})
        H.type_row(ws, r + 1, {"A": 4, "B": "SURVEYOR", "C": "HR", "D": 70})
    problems = _problems(big, repeat)
    assert [p.row is not None for p in problems] == [True, True]
    assert all("changed or added" in p.message for p in problems)


def test_a_deleted_heading_row_does_not_report_a_rate_deleted(big):
    wb = H.open_book(big)
    ws = wb[H.RT_TAB]
    ws.delete_rows(_title_row(ws, "Labor rates") + 1)
    H.save_book(wb, big)
    assert H.read(big).ops == []      # the headings are labels; every rate is intact
