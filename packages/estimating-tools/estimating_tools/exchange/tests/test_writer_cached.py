"""``writer.write_cached``: cached values on formula cells, nothing else."""
from __future__ import annotations

import zipfile

import pytest
from openpyxl import Workbook, load_workbook

from estimating_tools.exchange import writer


def _book(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws["A1"], ws["A2"] = 2, "=A1*3"
    ws["B1"], ws["B2"], ws["B3"], ws["B4"] = '="x"&A1', "=A1>1", "=1/0", "=TODAY()"
    ws["C1"] = "text"
    other = wb.create_sheet("Other")
    other["A1"] = "=Sheet!A1"
    wb.save(path)
    return path


def _parts(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


def test_values_are_cached_with_their_types(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    n = writer.write_cached(path, {"Sheet": {"A2": 6, "B1": "x2", "B2": True,
                                             "B3": writer.CachedError("#DIV/0!")},
                                   "Other": {"A1": 2.5}})
    assert n == 5
    values = load_workbook(path, data_only=True)
    ws = values["Sheet"]
    assert (ws["A2"].value, ws["B1"].value, ws["B2"].value, ws["B3"].value) \
        == (6, "x2", True, "#DIV/0!")
    assert ws["B4"].value is None                       # not given: no value
    assert values["Other"]["A1"].value == 2.5
    formulas = load_workbook(path)["Sheet"]
    assert formulas["A2"].value == "=A1*3" and formulas["C1"].value == "text"


def test_a_value_not_given_is_removed(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    writer.write_cached(path, {"Sheet": {"A2": 6, "B4": 45000}})
    writer.write_cached(path, {"Sheet": {"A2": 7}})
    ws = load_workbook(path, data_only=True)["Sheet"]
    assert ws["A2"].value == 7 and ws["B4"].value is None


def test_only_the_sheets_change(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    before = _parts(path)
    writer.write_cached(path, {"Sheet": {"A2": 6}})
    after = _parts(path)
    assert set(before) == set(after)
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"}


def test_a_value_for_a_cell_without_a_formula_is_refused(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Sheet!C1"):
        writer.write_cached(path, {"Sheet": {"A2": 6, "C1": 1}})
    with pytest.raises(KeyError):
        writer.write_cached(path, {"Nope": {"A1": 1}})
    with pytest.raises(ValueError, match="finite"):
        writer.write_cached(path, {"Sheet": {"A2": float("nan")}})
    assert path.read_bytes() == before
