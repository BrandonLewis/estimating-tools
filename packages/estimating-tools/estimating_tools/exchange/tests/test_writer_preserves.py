"""The spec's Patch fixture: a book holding an extra sheet, a note in a spare
column, a custom number format, a data-validation extension and a chart. A
cell write changes nothing outside the written sheet and the custom
properties; a row insert moves the note, the chart's series, the extension's
range and the number format with the rows and leaves the other parts byte
for byte."""
from __future__ import annotations

import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.packaging.custom import StringProperty

from estimating_tools.exchange import rowops, writer

#: An Excel 2010 list validation, as Excel writes one that reads another sheet.
X14 = (b'<extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}" '
       b'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
       b'<x14:dataValidations count="1" '
       b'xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">'
       b'<x14:dataValidation type="list" allowBlank="1" showErrorMessage="1">'
       b'<x14:formula1><xm:f>Lists!$A$1:$A$3</xm:f></x14:formula1>'
       b'<xm:sqref>C5:C30</xm:sqref></x14:dataValidation></x14:dataValidations>'
       b'</ext></extLst>')
SHEET = "xl/worksheets/sheet1.xml"


def _fixture(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Cost Report"
    for r in range(5, 31):
        ws[f"A{r}"] = f"line {r}"
        ws[f"D{r}"] = r * 10
    ws["D31"] = "=SUM(D5:D30)"
    ws["E12"] = 0.125
    ws["E12"].number_format = '0.000" t"'
    ws["H20"].comment = Comment("estimator: check this quantity", "est")
    lists = wb.create_sheet("Lists")
    for r, v in enumerate(("a", "b", "c"), start=1):
        lists[f"A{r}"] = v
    extra = wb.create_sheet("Estimator notes")
    extra["A1"] = "kept as typed"
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=4, min_row=5, max_row=30))
    extra.add_chart(chart, "C3")
    proto = wb.create_sheet("_templates")
    proto["A2"] = "new line"
    proto["D2"] = 0
    wb.custom_doc_props.append(StringProperty(name="exported_at", value="2026-11-01T00:00:00Z"))
    path = tmp_path / "fixture.xlsx"
    wb.save(path)
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts[SHEET] = parts[SHEET].replace(b"</worksheet>", X14 + b"</worksheet>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return path


def _parts(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_a_cell_write_leaves_every_other_part_byte_for_byte(tmp_path):
    path = _fixture(tmp_path)
    before = _parts(path)
    writer.write(path, {"Cost Report": {"X5": 41, "Y5": "0123456789abcdef"}},
                 properties={"exported_at": "2026-11-05T00:00:00Z"})
    after = _parts(path)
    assert {n for n in before if before[n] != after[n]} == {SHEET, "docProps/custom.xml"}
    assert b"<xm:sqref>C5:C30</xm:sqref>" in after[SHEET]
    assert b"<xm:f>Lists!$A$1:$A$3</xm:f>" in after[SHEET]
    ws = load_workbook(path)["Cost Report"]
    assert ws["X5"].value == 41 and ws["Y5"].value == "0123456789abcdef"
    assert ws["E12"].number_format == '0.000" t"'


def test_a_row_insert_moves_the_note_the_chart_and_the_extension(tmp_path):
    path = _fixture(tmp_path)
    before = _parts(path)
    writer.edit(path, rows=[rowops.InsertRows("Cost Report", 10, "_templates", 2, 2)])
    after = _parts(path)
    assert b"<xm:sqref>C5:C31</xm:sqref>" in after[SHEET]
    assert b"<xm:f>Lists!$A$1:$A$3</xm:f>" in after[SHEET]
    chart = next(n for n in after if n.startswith("xl/charts/chart"))
    assert b"'Cost Report'!$D$5:$D$31" in after[chart]
    ws = load_workbook(path)["Cost Report"]
    assert ws["H21"].comment.text == "estimator: check this quantity"
    assert ws["E13"].number_format == '0.000" t"' and ws["E13"].value == 0.125
    assert ws["A10"].value == "new line" and ws["D32"].value == "=SUM(D5:D31)"
    for name in ("xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml", "xl/styles.xml"):
        assert before[name] == after[name], name
