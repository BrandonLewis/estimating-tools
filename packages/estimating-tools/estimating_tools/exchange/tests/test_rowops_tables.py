"""A table an insert lands inside grows with its auto filter, as Excel grows
it; a delete that cuts one is still refused."""
from __future__ import annotations

import re
import zipfile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.worksheet.table import Table

from estimating_tools.exchange import rowops, writer


def _book(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Flat"
    ws["A4"], ws["B4"] = "Item", "Cost"
    ws["D1"] = "=SUM(B4:B5)"
    ws.add_table(Table(displayName="hc_flat", ref="A4:B5"))
    ws.conditional_formatting.add("B4:B5", CellIsRule(operator="equal", formula=['"OK"']))
    tpl = wb.create_sheet("_templates")
    tpl["A2"], tpl["B2"] = "x", "=1+1"
    path = tmp_path / "book.xlsx"
    wb.save(path)
    return path


def test_an_insert_inside_a_table_grows_it_and_its_filter(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[rowops.InsertRows(sheet="Flat", before=5, source="_templates",
                                              first=2, last=2, times=3)])
    with zipfile.ZipFile(path) as z:
        table = next(n for n in z.namelist() if "/tables/" in n)
        refs = re.findall(rb'ref="([^"]+)"', z.read(table))
        sheet = z.read("xl/worksheets/sheet1.xml")
    assert refs == [b"A4:B8", b"A4:B8"]                   # the table and its autoFilter
    assert b'sqref="B4:B8"' in sheet and b"<f>SUM(B4:B8)</f>" in sheet
    assert load_workbook(path)["Flat"].tables["hc_flat"].ref == "A4:B8"


def test_a_delete_that_cuts_a_table_is_still_refused(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    with pytest.raises(rowops.RowOpError, match="does not resize tables"):
        writer.edit(path, rows=[rowops.DeleteRows(sheet="Flat", first=5)])
    assert path.read_bytes() == before
