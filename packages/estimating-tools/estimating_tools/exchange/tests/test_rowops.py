"""Row inserts and deletes on an .xlsx package (``exchange.rowops``, through
``writer.edit``)."""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, FormulaRule
from openpyxl.styles import PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.worksheet.table import Table

from estimating_tools.exchange import rowops, writer

NS = writer.NS


def test_row_map_follows_rows_through_inserts_and_deletes():
    ops = [rowops.InsertRows("S", 10, "T", 3, 3, times=2), rowops.DeleteRows("S", 5),
           rowops.DeleteRows("Other", 1)]
    m = rowops.RowMap(ops)
    assert m.row("S", 4) == 4
    assert m.row("S", 5) is None
    assert m.row("S", 9) == 8
    assert m.row("S", 10) == 11          # pushed down by 2, then up by 1
    assert m.inserted(0) == [9, 10]
    assert m.row("Other", 3) == 2
    with pytest.raises(ValueError):
        m.inserted(1)


def test_ops_refuse_nonsense():
    with pytest.raises(ValueError):
        rowops.InsertRows("S", 0, "T", 1, 1)
    with pytest.raises(ValueError):
        rowops.InsertRows("S", 3, "S", 1, 1)
    with pytest.raises(ValueError):
        rowops.InsertRows("S", 3, "T", 4, 2)
    with pytest.raises(ValueError):
        rowops.DeleteRows("S", 2, 0)
    assert rowops.InsertRows("S", 3, "T", 4, 6, times=2).count == 6
    assert rowops.DeleteRows("S", 2, 3).last == 4


def _book(tmp_path, name="rows.xlsx"):
    """``Sheet`` with values 1..12 in A, a sum, a row formula, a merge, a
    validation, a conditional format and a number format; ``Proto`` holds one
    prototype row (3) with a formula, a string, a number and its own
    validation."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    for r in range(1, 13):
        ws[f"A{r}"] = r
    ws["B12"] = "=SUM(A1:A11)"
    ws["C5"] = "=A5*2"
    ws.merge_cells("D2:E3")
    dv = DataValidation(type="list", formula1='"a,b"')
    ws.add_data_validation(dv)
    dv.add("F4:F11")
    ws.conditional_formatting.add("G4:G11", CellIsRule(
        operator="equal", formula=["A4"], fill=PatternFill("solid", fgColor="FFFF0000")))
    ws["H6"] = 1.5
    ws["H6"].number_format = "0.000"
    proto = wb.create_sheet("Proto")
    proto["A3"] = "=A2+1"
    proto["B3"] = "proto"
    proto["C3"] = 7
    pdv = DataValidation(type="list", formula1='"x,y"')
    proto.add_data_validation(pdv)
    pdv.add("B3")
    path = tmp_path / name
    wb.save(path)
    return path


def _sqrefs(validations):
    return sorted(str(dv.sqref) for dv in validations.dataValidation)


def test_insert_copies_prototype_rows_and_moves_everything_below(tmp_path):
    path = _book(tmp_path)
    done = writer.edit(path, rows=[rowops.InsertRows("Sheet", 6, "Proto", 3, 3, times=2)])
    assert done.cells_written == 0 and done.lost == []
    ws = load_workbook(path)["Sheet"]
    assert ws["A6"].value == "=A5+1" and ws["A7"].value == "=A6+1"
    assert ws["B6"].value == "proto" and ws["C7"].value == 7
    assert ws["A8"].value == 6 and ws["A14"].value == 12
    assert ws["B14"].value == "=SUM(A1:A13)"
    assert ws["C5"].value == "=A5*2"
    assert ws["H8"].value == 1.5 and ws["H8"].number_format == "0.000"
    assert [str(r) for r in ws.merged_cells.ranges] == ["D2:E3"]
    assert _sqrefs(ws.data_validations) == ["B6:B7", "F4:F13"]
    assert [str(cf.sqref) for cf in ws.conditional_formatting] == ["G4:G13"]


def test_delete_moves_rows_up_and_shrinks_ranges(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 5, 2)])
    ws = load_workbook(path)["Sheet"]
    assert ws["A5"].value == 7 and ws["A10"].value == 12
    assert ws["B10"].value == "=SUM(A1:A9)"
    assert ws["C5"].value is None
    assert _sqrefs(ws.data_validations) == ["F4:F9"]
    assert [str(cf.sqref) for cf in ws.conditional_formatting] == ["G4:G9"]


def _refused(path, ops, text, **kw):
    before = path.read_bytes()
    with pytest.raises(rowops.RowOpError, match=text):
        writer.edit(path, rows=ops, **kw)
    assert path.read_bytes() == before


def test_a_cut_merge_or_array_formula_is_refused(tmp_path):
    path = _book(tmp_path)
    wb = load_workbook(path)
    wb["Sheet"].merge_cells("D8:D9")
    wb["Sheet"]["J1"] = ArrayFormula("J1:J3", "=A1:A3*2")
    wb.save(path)
    _refused(path, [rowops.InsertRows("Sheet", 9, "Proto", 3, 3)], "merged cells")
    _refused(path, [rowops.DeleteRows("Sheet", 8)], "merged cells")
    _refused(path, [rowops.InsertRows("Sheet", 2, "Proto", 3, 3)], "array formula")


def test_a_lost_reference_on_the_edited_sheet_is_refused(tmp_path):
    path = _book(tmp_path)
    wb = load_workbook(path)
    wb["Sheet"]["D1"] = "=A7"
    wb.save(path)
    _refused(path, [rowops.DeleteRows("Sheet", 7)], r"Sheet!D1")


def _rewrite_part(path, name, fn):
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts[name] = fn(parts[name])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in parts.items():
            z.writestr(n, data)


def _with_shared_formula(data: bytes) -> bytes:
    """K1:K3 share ``A1*3`` (Excel's shared formula; openpyxl never writes one)."""
    ET.register_namespace("", NS)
    root = ET.fromstring(data)
    rows = {int(r.get("r")): r for r in root.iter(f"{{{NS}}}row")}
    for r in (1, 2, 3):
        c = ET.SubElement(rows[r], f"{{{NS}}}c", r=f"K{r}")
        f = ET.SubElement(c, f"{{{NS}}}f", t="shared", si="0")
        if r == 1:
            f.set("ref", "K1:K3")
            f.text = "A1*3"
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def test_shared_formulas_are_expanded_before_they_move(tmp_path):
    path = _book(tmp_path)
    _rewrite_part(path, "xl/worksheets/sheet1.xml", _with_shared_formula)
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 2, "Proto", 3, 3)])
    ws = load_workbook(path)["Sheet"]
    assert ws["K1"].value == "=A1*3"
    assert ws["K3"].value == "=A3*3" and ws["K4"].value == "=A4*3"
    with zipfile.ZipFile(path) as z:
        assert b't="shared"' not in z.read("xl/worksheets/sheet1.xml")


CALC = (b'<?xml version="1.0" encoding="UTF-8"?><calcChain xmlns="' + NS.encode()
        + b'"><c r="B12" i="1"/></calcChain>')


def _with_calc_chain(path):
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["xl/calcChain.xml"] = CALC
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>", b'<Override PartName="/xl/calcChain.xml" ContentType="application/'
                     b'vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml"/></Types>')
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        b"</Relationships>", b'<Relationship Id="rIdCalc" Type="http://schemas.openxmlformats.'
                             b'org/officeDocument/2006/relationships/calcChain" '
                             b'Target="calcChain.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in parts.items():
            z.writestr(n, data)


def test_the_calc_chain_is_dropped_and_a_full_calculation_asked_for(tmp_path):
    path = _book(tmp_path)
    _with_calc_chain(path)
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 4)])
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert "xl/calcChain.xml" not in names
        assert b"calcChain" not in z.read("[Content_Types].xml")
        assert b"calcChain" not in z.read("xl/_rels/workbook.xml.rels")
        assert b'fullCalcOnLoad="1"' in z.read("xl/workbook.xml")
    load_workbook(path)


def test_a_format_whose_first_row_is_deleted_keeps_reading_its_own_row(tmp_path):
    # G4:G11's rule reads A4 (its own row): deleting row 4, Excel re-anchors
    # the rule on the new top-left cell, so it still reads its own row.
    path = _book(tmp_path)
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 4)])
    (cf,) = list(load_workbook(path)["Sheet"].conditional_formatting)
    assert str(cf.sqref) == "G4:G10" and cf.rules[0].formula == ["A4"]


def test_row_ops_then_cells_in_one_rewrite(tmp_path):
    path = _book(tmp_path)
    done = writer.edit(path, rows=[rowops.InsertRows("Sheet", 6, "Proto", 3, 3)],
                       cells={"Sheet": {"D6": "typed into the new row"}})
    assert done.cells_written == 1
    ws = load_workbook(path)["Sheet"]
    assert ws["D6"].value == "typed into the new row" and ws["B6"].value == "proto"


C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
XDR_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"


def _decorated(tmp_path, name="deco.xlsx"):
    """``_book`` plus: another sheet pointing into Sheet, a defined name, a
    chart over A4:A11 anchored at J9, a note at H15, a table at L20:M22."""
    path = _book(tmp_path, name)
    wb = load_workbook(path)
    ws = wb["Sheet"]
    notes = wb.create_sheet("Notes")
    notes["A1"] = "=Sheet!A10"
    wb.defined_names["blk"] = DefinedName("blk", attr_text="Sheet!$A$4:$A$11")
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=1, min_row=4, max_row=11))
    ws.add_chart(chart, "J9")
    ws["H15"].comment = Comment("estimator's note", "me")
    ws["L20"], ws["M20"] = "h1", "h2"
    ws["L21"], ws["M21"], ws["L22"], ws["M22"] = 1, 2, 3, 4
    ws.add_table(Table(displayName="T1", ref="L20:M22"))
    wb.save(path)
    return path


def _xml(path, prefix):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.startswith(prefix) and n.endswith(".xml"))
        return ET.fromstring(z.read(name)), z.read(name)


def _vml(path) -> bytes:
    """The note's VML drawing (whatever openpyxl named it)."""
    with zipfile.ZipFile(path) as z:
        return z.read(next(n for n in z.namelist() if n.endswith(".vml")))


def test_an_insert_moves_other_sheets_names_charts_notes_drawings_and_tables(tmp_path):
    path = _decorated(tmp_path)
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 5, "Proto", 3, 3)])
    wb = load_workbook(path)
    assert wb["Notes"]["A1"].value == "=Sheet!A11"
    assert wb.defined_names["blk"].attr_text == "Sheet!$A$4:$A$12"
    assert wb["Sheet"]["H16"].comment.text == "estimator's note"
    assert wb["Sheet"].tables["T1"].ref == "L21:M23"
    chart, _raw = _xml(path, "xl/charts/chart")
    assert [f.text for f in chart.iter(f"{{{C_NS}}}f")] == ["'Sheet'!$A$4:$A$12"]
    drawing, _raw = _xml(path, "xl/drawings/drawing")
    assert [r.text for r in drawing.iter(f"{{{XDR_NS}}}row")][0] == "9"
    assert re.search(rb"<(?:\w+:)?Row>\s*15\s*</(?:\w+:)?Row>", _vml(path))


def test_a_delete_under_a_chart_or_a_note_is_refused(tmp_path):
    path = _decorated(tmp_path)
    _refused(path, [rowops.DeleteRows("Sheet", 9)], "anchored")
    _refused(path, [rowops.DeleteRows("Sheet", 15)], "note")
    # An insert inside a table grows it (test_rowops_tables); a delete of
    # one of its rows is refused.
    _refused(path, [rowops.DeleteRows("Sheet", 21)], "table T1")


def test_a_lost_reference_on_another_sheet_needs_lost_ok(tmp_path):
    path = _decorated(tmp_path)
    _refused(path, [rowops.DeleteRows("Sheet", 10)], r"Notes!A1")
    done = writer.edit(path, rows=[rowops.DeleteRows("Sheet", 10)], lost_ok=("Notes",))
    assert done.lost == [("Notes", "A1", "Sheet!#REF!")]
    wb = load_workbook(path)
    assert wb["Notes"]["A1"].value == "=Sheet!#REF!"
    assert wb.defined_names["blk"].attr_text == "Sheet!$A$4:$A$10"


PIVOT = (b'<?xml version="1.0" encoding="UTF-8"?><pivotCacheDefinition xmlns="' + NS.encode()
         + b'"><cacheSource type="worksheet"><worksheetSource ref="A1:B9" sheet="Sheet"/>'
         + b'</cacheSource></pivotCacheDefinition>')


def test_a_pivot_reading_the_sheet_is_refused(tmp_path):
    path = _book(tmp_path)
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("xl/pivotCache/pivotCacheDefinition1.xml", PIVOT)
    _refused(path, [rowops.DeleteRows("Sheet", 4)], "pivot table")


def test_untouched_parts_stay_byte_for_byte(tmp_path):
    path = _decorated(tmp_path)
    with zipfile.ZipFile(path) as z:
        before = {n: z.read(n) for n in z.namelist()}
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 30, "Proto", 3, 3)])
    with zipfile.ZipFile(path) as z:
        after = {n: z.read(n) for n in z.namelist()}
    changed = {n for n in before if before[n] != after.get(n)}
    # Row 30 is below everything decorated: only the sheet changes (and the
    # workbook part, were full calculation on load not already set -- openpyxl
    # sets it).
    assert "xl/worksheets/sheet1.xml" in changed
    assert changed <= {"xl/worksheets/sheet1.xml", "xl/workbook.xml"}


# --- PR #444 review: Copilot's threads and the review against real Excel ---


def _sheet_xml(path, name="xl/worksheets/sheet1.xml") -> bytes:
    with zipfile.ZipFile(path) as z:
        return z.read(name)


def test_an_insert_past_the_last_row_is_refused(tmp_path):
    path = _book(tmp_path)
    _refused(path, [rowops.InsertRows("Sheet", 1048576, "Proto", 3, 3, times=2)], "last row")
    with pytest.raises(ValueError):
        rowops.InsertRows("S", 3, "T", 1048576, 1048577)


def _array_book(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    for r in range(1, 7):
        ws[f"A{r}"] = r
    ws["J1"] = ArrayFormula("J1:J3", "=A1:A3*2")
    wb.create_sheet("Proto")["A1"] = 1
    path = tmp_path / "array.xlsx"
    wb.save(path)
    return path


def test_deleting_part_of_an_array_is_refused_and_all_of_it_is_not(tmp_path):
    path = _array_book(tmp_path)
    _refused(path, [rowops.DeleteRows("Sheet", 1)], "array formula")
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 1, 3)])
    ws = load_workbook(path)["Sheet"]
    assert ws["J1"].value is None and ws["A1"].value == 4


def test_a_format_reanchored_across_ranges_keeps_its_column_offset(tmp_path):
    path = _book(tmp_path)
    wb = load_workbook(path)
    wb["Sheet"].conditional_formatting.add("B4 D5:D11", FormulaRule(
        formula=["A4>0"], fill=PatternFill("solid", fgColor="FF00FF00")))
    wb.save(path)
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 4)])
    rules = {str(cf.sqref): cf.rules[0].formula
             for cf in load_workbook(path)["Sheet"].conditional_formatting}
    assert rules["D4:D10"] == ["C4>0"]


def test_a_colour_scale_threshold_formula_moves_and_cannot_be_lost(tmp_path):
    path = _book(tmp_path)
    wb = load_workbook(path)
    wb["Sheet"].conditional_formatting.add("H4:H11", ColorScaleRule(
        start_type="formula", start_value="$A$5", start_color="FFFF0000",
        end_type="max", end_color="FF00FF00"))
    wb.save(path)
    copy_ = tmp_path / "copy.xlsx"
    copy_.write_bytes(path.read_bytes())
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 5, "Proto", 3, 3)])
    assert b'val="$A$6"' in _sheet_xml(path)
    _refused(copy_, [rowops.DeleteRows("Sheet", 5)], "conditional format")


def test_an_emptied_ignored_error_is_removed(tmp_path):
    path = _book(tmp_path)
    _rewrite_part(path, "xl/worksheets/sheet1.xml", lambda d: d.replace(
        b"</worksheet>", b'<ignoredErrors><ignoredError sqref="H5" numberStoredAsText="1"/>'
                         b'<ignoredError sqref="H8" formula="1"/></ignoredErrors></worksheet>'))
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 5)])
    data = _sheet_xml(path)
    assert data.count(b"<ignoredError ") == 1 and b'sqref="H7"' in data
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 7)])
    assert b"ignoredError" not in _sheet_xml(path)
    load_workbook(path)


def _validated_proto(tmp_path, existing=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    for r in range(1, 10):
        ws[f"A{r}"] = r
    if existing:
        dv = DataValidation(type="custom", formula1=existing[1])
        ws.add_data_validation(dv)
        dv.add(existing[0])
    proto = wb.create_sheet("Proto")
    proto["B3"] = 0
    pdv = DataValidation(type="custom", formula1="A3>0")
    proto.add_data_validation(pdv)
    pdv.add("B3")
    path = tmp_path / "dv.xlsx"
    wb.save(path)
    return path


def test_a_copied_validation_reads_its_own_row(tmp_path):
    path = _validated_proto(tmp_path)
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 6, "Proto", 3, 3, times=2)])
    (dv,) = load_workbook(path)["Sheet"].data_validations.dataValidation
    assert str(dv.sqref) == "B6:B7" and dv.formula1 == "A6>0"


UID = b' xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" xr:uid='


def test_a_copied_validation_merges_with_its_twin_whatever_its_uid(tmp_path):
    path = _validated_proto(tmp_path, existing=("B2:B4", "A2>0"))
    for n, uid in (("xl/worksheets/sheet1.xml", b'"{AAAA}"'),
                   ("xl/worksheets/sheet2.xml", b'"{BBBB}"')):
        _rewrite_part(path, n, lambda d, uid=uid: d.replace(
            b"<dataValidation ", b"<dataValidation" + UID + uid + b" ", 1))
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 5, "Proto", 3, 3)])
    data = _sheet_xml(path)
    assert data.count(b"<dataValidation ") == 1 and b'sqref="B2:B4 B5"' in data


def test_the_dimension_covers_rows_appended_below(tmp_path):
    path = _book(tmp_path)
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 30, "Proto", 3, 3)])
    assert re.search(rb'<dimension ref="A1:H30"\s*/>', _sheet_xml(path))


X14_RULES = (b'<extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}" '
             b'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
             b'<x14:dataValidations count="2" '
             b'xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">'
             b'<x14:dataValidation type="custom"><x14:formula1><xm:f>A4&gt;0</xm:f>'
             b'</x14:formula1><xm:sqref>C4:C11</xm:sqref></x14:dataValidation>'
             b'<x14:dataValidation type="custom"><x14:formula1><xm:f>A5&gt;0</xm:f>'
             b'</x14:formula1><xm:sqref>K5</xm:sqref></x14:dataValidation>'
             b'</x14:dataValidations></ext></extLst>')


def test_an_x14_rule_is_reanchored_and_an_emptied_one_removed(tmp_path):
    path = _book(tmp_path)
    _rewrite_part(path, "xl/worksheets/sheet1.xml",
                  lambda d: d.replace(b"</worksheet>", X14_RULES + b"</worksheet>"))
    copy_ = tmp_path / "copy.xlsx"
    copy_.write_bytes(path.read_bytes())
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 4)])
    data = _sheet_xml(path)
    assert b"<xm:f>A4&gt;0</xm:f></x14:formula1><xm:sqref>C4:C10</xm:sqref>" in data
    writer.edit(copy_, rows=[rowops.DeleteRows("Sheet", 5)])
    data = _sheet_xml(copy_)
    assert b"K5" not in data and b'x14:dataValidations count="1"' in data
    assert b"<xm:f>A4&gt;0</xm:f></x14:formula1><xm:sqref>C4:C10</xm:sqref>" in data


def _two_cell_chart(data: bytes) -> bytes:
    data = data.replace(b"oneCellAnchor", b"twoCellAnchor")
    return re.sub(rb"<ext [^>]*/>", b"<to><col>15</col><colOff>0</colOff><row>11</row>"
                                     b"<rowOff>5000</rowOff></to>", data)


def test_a_drawing_bottom_on_a_deleted_row_moves_to_the_row_below(tmp_path):
    path = _decorated(tmp_path)
    _rewrite_part(path, "xl/drawings/drawing1.xml", _two_cell_chart)
    writer.edit(path, rows=[rowops.DeleteRows("Sheet", 12)])
    data = _sheet_xml(path, "xl/drawings/drawing1.xml")
    assert b"<to><col>15</col><colOff>0</colOff><row>11</row><rowOff>0</rowOff></to>" in data


def test_lost_cells_follow_later_ops(tmp_path):
    path = _book(tmp_path)
    wb = load_workbook(path)
    wb["Sheet"]["D20"] = "=A7+A12"
    wb.save(path)
    copy_ = tmp_path / "copy.xlsx"
    copy_.write_bytes(path.read_bytes())
    done = writer.edit(path, rows=[rowops.DeleteRows("Sheet", 7), rowops.DeleteRows("Sheet", 1)],
                       lost_ok=("Sheet",))
    assert done.lost == [("Sheet", "D18", "#REF!+A10")]
    assert load_workbook(path)["Sheet"]["D18"].value == "=#REF!+A10"
    done = writer.edit(copy_, rows=[rowops.DeleteRows("Sheet", 7),
                                    rowops.DeleteRows("Sheet", 19)])
    assert done.lost == []


def _offset_rules(tmp_path):
    """The review's Excel case: a rule on C2:C19 reading the row above, a
    validation on G25:G30 reading another sheet's row, a same-row rule on
    E2:E19."""
    path = _book(tmp_path, "offset.xlsx")
    wb = load_workbook(path)
    ws = wb["Sheet"]
    other = wb.create_sheet("Other")
    other["A1"] = 1
    ws.conditional_formatting.add("C2:C19", FormulaRule(
        formula=["C1>5"], fill=PatternFill("solid", fgColor="FFFFFF00")))
    ws.conditional_formatting.add("E2:E19", FormulaRule(
        formula=["A2>5"], fill=PatternFill("solid", fgColor="FFFFFF00")))
    dv = DataValidation(type="custom", formula1="Other!A25>0")
    ws.add_data_validation(dv)
    dv.add("G25:G30")
    wb.save(path)
    return path


def test_a_rule_reading_another_row_refuses_an_op_inside_its_range(tmp_path):
    # Excel splits such a rule in two (C2:C4 C6:C19 and C5); the writer
    # does not split, so it refuses and says which rule.
    path = _offset_rules(tmp_path)
    _refused(path, [rowops.DeleteRows("Sheet", 5)], r"Sheet.*C2:C19.*C1>5")
    _refused(path, [rowops.InsertRows("Sheet", 5, "Proto", 3, 3)], r"C2:C19.*C1>5")
    _refused(path, [rowops.InsertRows("Sheet", 27, "Proto", 3, 3)], r"G25:G30.*Other!A25>0")
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 40, "Proto", 3, 3)])
    rules = {str(cf.sqref): cf.rules[0].formula
             for cf in load_workbook(path)["Sheet"].conditional_formatting}
    assert rules["C2:C19"] == ["C1>5"] and rules["E2:E19"] == ["A2>5"]


def test_a_rule_reading_its_own_row_moves_with_an_op_inside_it(tmp_path):
    path = _book(tmp_path, "own.xlsx")
    wb = load_workbook(path)
    wb["Sheet"].conditional_formatting.add("E2:E19", FormulaRule(
        formula=["A2>5"], fill=PatternFill("solid", fgColor="FFFFFF00")))
    wb.save(path)
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 5, "Proto", 3, 3)])
    rules = {str(cf.sqref): cf.rules[0].formula
             for cf in load_workbook(path)["Sheet"].conditional_formatting}
    assert rules["E2:E20"] == ["A2>5"]


PIVOT_TABLE = (b'<?xml version="1.0" encoding="UTF-8"?><pivotTableDefinition xmlns="' + NS.encode()
               + b'" name="PT1" cacheId="1"><location ref="A20:B25" firstHeaderRow="1" '
               + b'firstDataRow="1" firstDataCol="1"/></pivotTableDefinition>')


def test_a_pivot_table_on_the_edited_sheet_is_refused(tmp_path):
    path = _book(tmp_path)
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("xl/pivotTables/pivotTable1.xml", PIVOT_TABLE)
        z.writestr("xl/worksheets/_rels/sheet1.xml.rels",
                   b'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
                   b'openxmlformats.org/package/2006/relationships"><Relationship Id="rId9" '
                   b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   b'pivotTable" Target="../pivotTables/pivotTable1.xml"/></Relationships>')
    _refused(path, [rowops.InsertRows("Sheet", 2, "Proto", 3, 3)], "pivot table")


def test_the_view_stays_where_it_was(tmp_path):
    # Excel moves neither a frozen pane's top-left cell nor the selection on
    # a row insert (checked in Excel 365, PR #444 review).
    path = _book(tmp_path)
    wb = load_workbook(path)
    wb["Sheet"].freeze_panes = "A2"
    wb.save(path)
    def view():
        found = re.search(rb"<sheetView.*?</sheetView>", _sheet_xml(path)).group(0)
        return re.sub(rb"\s+/>", b"/>", found)

    before = view()
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 2, "Proto", 3, 3)])
    assert view() == before


def test_a_3d_reference_is_refused_only_when_it_spans_the_edited_sheet(tmp_path):
    path = _decorated(tmp_path)
    wb = load_workbook(path)
    wb["Notes"]["A2"] = "=SUM(Proto:Notes!A5)"
    wb.save(path)
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 2, "Proto", 3, 3)])
    assert load_workbook(path)["Notes"]["A2"].value == "=SUM(Proto:Notes!A5)"
    wb = load_workbook(path)
    wb["Notes"]["A3"] = "=SUM(Sheet:Proto!A5)"
    wb.save(path)
    _refused(path, [rowops.InsertRows("Sheet", 2, "Proto", 3, 3)], r"Notes!A3.*3-D")


def test_a_copied_cell_already_inside_its_twin_is_not_listed_again(tmp_path):
    # The insert lands inside B2:B9, which grows to B2:B10 and so covers the
    # copied cell already, as in Excel.
    path = _validated_proto(tmp_path, existing=("B2:B9", "A2>0"))
    writer.edit(path, rows=[rowops.InsertRows("Sheet", 5, "Proto", 3, 3)])
    data = _sheet_xml(path)
    assert data.count(b"<dataValidation ") == 1 and b'sqref="B2:B10"' in data
