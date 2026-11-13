"""``rowops.FillRows``: a template fill's rows, each a copy of its own
prototype row, inserted in one op -- the rest of the package moves as for
any insert, and each copy's formulas are placed against its block."""
from __future__ import annotations

import zipfile
from xml.etree import ElementTree as ET

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from estimating_tools.exchange import rowops, writer

NS = writer.NS


def _book(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    ws["A1"] = "heading"
    ws["B1"] = "amount"
    ws["D1"] = "=SUM(B1:B2)"                 # header..first_row: grows with the rows
    other = wb.create_sheet("Other")
    other["A1"] = "=SUM(S!B1:B2)"
    tpl = wb.create_sheet("_templates")
    tpl["A2"], tpl["B2"] = "OWNER", "=SUM(B3:B5)"
    tpl["A3"] = "START"
    tpl["A4"], tpl["B4"] = "LINE", "=C4*2"
    tpl["A5"] = "END"
    dv = DataValidation(type="list", formula1='"a,b"', allow_blank=True)
    dv.sqref = "C4"
    tpl.add_data_validation(dv)
    wb.defined_names["total"] = DefinedName("total", attr_text="S!$B$2")
    path = tmp_path / "book.xlsx"
    wb.save(path)
    return path


def _op(before=2, lines=2):
    block = ((2, 0), (3, 1), (5, 2 + lines))
    placed = [rowops.FillRow(2, block, 1), rowops.FillRow(3, block, 2)]
    placed += [rowops.FillRow(4, block, 2) for _ in range(lines)]
    placed.append(rowops.FillRow(5, block, 2))
    return rowops.FillRows("S", before, "_templates", placed)


def test_each_row_is_its_prototype_and_the_owner_sums_its_own_brackets(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[_op()])
    ws = load_workbook(path)["S"]
    assert [ws[f"A{r}"].value for r in range(2, 8)] == ["OWNER", "START", "LINE", "LINE",
                                                         "END", None]
    assert ws["B2"].value == "=SUM(B3:B6)"
    assert (ws["B4"].value, ws["B5"].value) == ("=C4*2", "=C5*2")


def test_the_rest_of_the_book_moves_as_for_any_insert(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[_op()])
    wb = load_workbook(path)
    assert wb["S"]["D1"].value == "=SUM(B1:B7)"
    assert wb["Other"]["A1"].value == "=SUM(S!B1:B7)"
    assert wb.defined_names["total"].attr_text == "S!$B$7"


def test_a_prototype_rows_validation_and_outline_level_come_along(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[_op()])
    ws = load_workbook(path)["S"]
    assert any("C4" in str(dv.sqref) and "C5" in str(dv.sqref)
               for dv in ws.data_validations.dataValidation)
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    levels = {row.get("r"): row.get("outlineLevel") for row in root.iter(f"{{{NS}}}row")}
    assert (levels["2"], levels["3"], levels["6"]) == ("1", "2", "2")


def test_a_block_with_no_lines_sums_its_markers(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[_op(lines=0)])
    assert load_workbook(path)["S"]["B2"].value == "=SUM(B3:B4)"


def test_the_row_map_and_the_count():
    op = _op(lines=3)
    assert op.count == 6 and (op.first, op.last) == (2, 5)
    assert rowops.RowMap([op]).inserted(0) == [2, 3, 4, 5, 6, 7]
    with pytest.raises(ValueError, match="no rows to place"):
        rowops.FillRows("S", 2, "_templates", [])


def _sheet_xml(path, part="xl/worksheets/sheet1.xml"):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(part))


def test_a_long_fills_validation_is_one_range_per_column(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[_op(lines=2000)])
    root = _sheet_xml(path)
    sqrefs = [dv.get("sqref") for dv in root.iter(f"{{{NS}}}dataValidation")]
    assert sqrefs == ["C4:C2003"]


def test_a_long_fill_with_validated_columns_is_quick(tmp_path):
    """Each copied cell was checked against every cell already in the
    validation's range list: 2,000 lines under three validated columns took
    about ten seconds."""
    import time

    wb = Workbook()
    wb.active.title = "S"
    wb["S"]["A1"] = "h"
    tpl = wb.create_sheet("_templates")
    tpl["A2"], tpl["B2"] = "OWNER", "=SUM(B3:B5)"
    tpl["A3"] = "START"
    tpl["A4"], tpl["B4"] = "LINE", "=C4*2"
    tpl["A5"] = "END"
    for col in "CDE":
        dv = DataValidation(type="list", formula1='"a,b"')
        dv.sqref = f"{col}4"
        tpl.add_data_validation(dv)
    path = tmp_path / "book.xlsx"
    wb.save(path)
    start = time.perf_counter()
    writer.edit(path, rows=[_op(lines=2000)])
    assert time.perf_counter() - start < 2.0
    # Three equivalent rules: one validation, one range per column.
    sqrefs = [dv.get("sqref") for dv in _sheet_xml(path).iter(f"{{{NS}}}dataValidation")]
    assert sqrefs == ["C4:C2003 D4:D2003 E4:E2003"]


def test_the_sheet_records_its_deepest_outline_level(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[_op()])
    fmt = _sheet_xml(path).find(f"{{{NS}}}sheetFormatPr")
    assert fmt.get("outlineLevelRow") == "2"


def test_a_sheet_without_a_format_record_gets_one_in_schema_order(tmp_path):
    path = _book(tmp_path)
    src = tmp_path / "src.xlsx"
    path.rename(src)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(path, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(data)
                root.remove(root.find(f"{{{NS}}}sheetFormatPr"))
                ET.register_namespace("", NS)
                data = ET.tostring(root, xml_declaration=True, encoding="UTF-8")
            zout.writestr(info, data)
    writer.edit(path, rows=[_op()])
    root = _sheet_xml(path)
    tags = [child.tag.split("}")[1] for child in root]
    assert tags.index("sheetViews") < tags.index("sheetFormatPr") < tags.index("sheetData")
    fmt = root.find(f"{{{NS}}}sheetFormatPr")
    assert fmt.get("outlineLevelRow") == "2" and fmt.get("defaultRowHeight")
    load_workbook(path)


def test_a_row_placed_at_level_zero_drops_the_prototypes_collapse_but_keeps_hidden(tmp_path):
    wb = load_workbook(_book(tmp_path))
    dim = wb["_templates"].row_dimensions[2]
    dim.outline_level, dim.collapsed, dim.hidden = 1, True, True
    path = tmp_path / "proto.xlsx"
    wb.save(path)
    block = ((2, 0), (3, 1), (5, 2))
    placed = [rowops.FillRow(2, block, 0), rowops.FillRow(3, block, 1),
              rowops.FillRow(5, block, 1)]
    writer.edit(path, rows=[rowops.FillRows("S", 2, "_templates", placed)])
    row = next(r for r in _sheet_xml(path).iter(f"{{{NS}}}row") if r.get("r") == "2")
    assert row.get("outlineLevel") is None and row.get("collapsed") is None
    assert row.get("hidden") == "1"
