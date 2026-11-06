from __future__ import annotations

import math
import os
import subprocess
import sys
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.packaging.custom import StringProperty

from estimating_tools.exchange import writer


def _book(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Cost Report"
    ws["A1"] = "keep"
    ws["X9"] = None
    ws["Y9"] = "old"
    ws["B2"] = "=A1&\"!\""
    other = wb.create_sheet("Notes")
    other["A1"] = "estimator's note"
    wb.custom_doc_props.append(StringProperty(name="exported_at", value="2026-10-31T00:00:00Z"))
    path = tmp_path / "b.xlsx"
    wb.save(path)
    return path


def _entries(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_write_cells_sets_values_and_leaves_every_other_part_alone(tmp_path):
    path = _book(tmp_path)
    before = _entries(path)
    n = writer.write_cells(path, {"Cost Report": {"X9": 41, "Y9": "abcd", "Z9": 2.5}})
    assert n == 3
    wb = load_workbook(path)
    ws = wb["Cost Report"]
    assert ws["X9"].value == 41 and ws["Y9"].value == "abcd" and ws["Z9"].value == 2.5
    assert ws["A1"].value == "keep" and ws["B2"].value == '=A1&"!"'
    assert wb["Notes"]["A1"].value == "estimator's note"
    after = _entries(path)
    changed = {k for k in before if before[k] != after.get(k)}
    assert changed == {"xl/worksheets/sheet1.xml"}


def test_write_cells_clears_with_none(tmp_path):
    path = _book(tmp_path)
    writer.write_cells(path, {"Cost Report": {"Y9": None}})
    assert load_workbook(path)["Cost Report"]["Y9"].value is None


def test_write_cells_refuses_an_unknown_sheet(tmp_path):
    path = _book(tmp_path)
    try:
        writer.write_cells(path, {"Nope": {"A1": 1}})
    except KeyError as exc:
        assert "Nope" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_set_custom_property_replaces_and_adds(tmp_path):
    path = _book(tmp_path)
    writer.set_custom_properties(path, {"exported_at": "2026-11-01T00:00:00Z", "new_prop": "x"})
    props = {p.name: p.value for p in load_workbook(path).custom_doc_props.props}
    assert props["exported_at"] == "2026-11-01T00:00:00Z" and props["new_prop"] == "x"


def test_write_is_atomic(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    try:
        writer.write_cells(path, {"Cost Report": {"not a ref": 1}})
    except ValueError:
        pass
    assert path.read_bytes() == before


def test_write_keeps_the_zip_entry_order_and_timestamps(tmp_path):
    path = _book(tmp_path)
    with zipfile.ZipFile(path) as z:
        before = [(i.filename, i.date_time) for i in z.infolist()]
    writer.write_cells(path, {"Cost Report": {"X9": 1}})
    with zipfile.ZipFile(path) as z:
        after = [(i.filename, i.date_time) for i in z.infolist()]
    assert before == after


def test_custom_properties_then_write_cells_keeps_the_sheet_namespace(tmp_path):
    path = _book(tmp_path)
    writer.set_custom_properties(path, {"exported_at": "2026-11-01T00:00:00Z"})
    writer.write_cells(path, {"Cost Report": {"X9": 7, "Y9": "z"}})
    with zipfile.ZipFile(path) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "<worksheet xmlns=" in sheet and "ns0:" not in sheet
    wb = load_workbook(path)
    assert wb["Cost Report"]["X9"].value == 7 and wb["Cost Report"]["Y9"].value == "z"
    props = {p.name: p.value for p in wb.custom_doc_props.props}
    assert props["exported_at"] == "2026-11-01T00:00:00Z"


def test_write_into_a_real_heavybook_stays_readable(tmp_path):
    from estimating_tools.exchange.reader import read_book
    from estimating_tools.heavybook.tests import _readback as H

    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    writer.write_cells(path, {H.CR_TAB: {"X9": 41}})
    assert load_workbook(path)[H.CR_TAB]["X9"].value == 41
    read_book(path)  # raises ReadRefused if the book is no longer readable


EXCEL_ROOT = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    b'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    b'mc:Ignorable="x14ac xr xr2 xr3" '
    b'xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" '
    b'xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" '
    b'xmlns:xr2="http://schemas.microsoft.com/office/spreadsheetml/2015/revision2" '
    b'xmlns:xr3="http://schemas.microsoft.com/office/spreadsheetml/2016/revision3" '
    b'xr:uid="{00000000-0001-0000-0000-000000000000}">'
)


def _start_tag_end(data):
    return writer._root_start_end(data)


def test_an_excel_decorated_sheet_keeps_its_prolog_root_and_prefixes(tmp_path):
    path = _book(tmp_path)
    sheet = _entries(path)["xl/worksheets/sheet1.xml"]
    body = sheet[_start_tag_end(sheet):].replace(
        b'<row r="9"', b'<row x14ac:dyDescent="0.25" r="9"', 1)
    assert b"x14ac:dyDescent" in body
    excel = EXCEL_ROOT + body
    writer._rewrite(path, {"xl/worksheets/sheet1.xml": excel})
    writer.write_cells(path, {"Cost Report": {"X9": 5}})
    out = _entries(path)["xl/worksheets/sheet1.xml"]
    assert out[:_start_tag_end(out)] == EXCEL_ROOT
    assert b'x14ac:dyDescent="0.25"' in out and b"ns1:" not in out
    assert out.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    assert load_workbook(path)["Cost Report"]["X9"].value == 5


def test_a_decorated_custom_xml_keeps_its_root(tmp_path):
    path = _book(tmp_path)
    old = _entries(path)["docProps/custom.xml"]
    root = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties '
            b'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
            b'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes" '
            b'xmlns:zz="urn:unused">')
    inner = old[_start_tag_end(old):]
    writer._rewrite(path, {"docProps/custom.xml": root + inner})
    writer.set_custom_properties(path, {"exported_at": "2026-11-02T00:00:00Z", "n": "1"})
    out = _entries(path)["docProps/custom.xml"]
    assert out[:_start_tag_end(out)] == root
    props = {p.name: p.value for p in load_workbook(path).custom_doc_props.props}
    assert props == {"exported_at": "2026-11-02T00:00:00Z", "n": "1"}


def test_formula_cells_are_refused_and_the_file_is_untouched(tmp_path):
    for label, xml in (
        ("plain", b'<c r="C1"><f>A1*2</f><v>0</v></c>'),
        ("master", b'<c r="C1"><f t="shared" ref="C1:C3" si="0">A1*2</f><v>0</v></c>'),
        ("follower", b'<c r="C1"><f t="shared" si="0"/><v>0</v></c>'),
    ):
        path = _book(tmp_path)
        sheet = _entries(path)["xl/worksheets/sheet1.xml"]
        assert b'<row r="1"' in sheet, label
        i = sheet.index(b"</row>", sheet.index(b'<row r="1"'))
        patched = sheet[:i] + xml + sheet[i:]
        writer._rewrite(path, {"xl/worksheets/sheet1.xml": patched})
        before = path.read_bytes()
        try:
            writer.write_cells(path, {"Cost Report": {"X9": 1, "C1": 9}})
        except ValueError as exc:
            assert "Cost Report!C1 holds a formula" in str(exc), label
        else:
            raise AssertionError(f"expected ValueError for {label}")
        assert path.read_bytes() == before, label


def test_writing_an_existing_formula_cell_is_refused_but_untouched_ones_survive(tmp_path):
    path = _book(tmp_path)
    try:
        writer.write_cells(path, {"Cost Report": {"B2": 1}})
    except ValueError as exc:
        assert "Cost Report!B2" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    writer.write_cells(path, {"Cost Report": {"X9": 1}})
    assert load_workbook(path)["Cost Report"]["B2"].value == '=A1&"!"'


def test_rebound_process_wide_prefixes_do_not_break_the_splice(tmp_path):
    from xml.etree import ElementTree as ET

    core = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    path = _book(tmp_path)
    sheet = _entries(path)["xl/worksheets/sheet1.xml"]
    body = sheet[_start_tag_end(sheet):]
    cust = _entries(path)["docProps/custom.xml"]
    cust_root = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties '
                 b'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
                 b'custom-properties" '
                 b'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
                 b'docPropsVTypes">')
    writer._rewrite(path, {"xl/worksheets/sheet1.xml": EXCEL_ROOT + body,
                           "docProps/custom.xml": cust_root + cust[_start_tag_end(cust):]})
    saved = dict(ET._namespace_map)
    try:
        ET.register_namespace("s", writer.NS)
        ET.register_namespace("cp", core)
        writer.write_cells(path, {"Cost Report": {"X9": 3}})
        writer.set_custom_properties(path, {"k": "v"})
    finally:
        ET._namespace_map.clear()
        ET._namespace_map.update(saved)
    parts = _entries(path)
    roots = (("xl/worksheets/sheet1.xml", EXCEL_ROOT), ("docProps/custom.xml", cust_root))
    for name, root in roots:
        ET.fromstring(parts[name])
        assert parts[name][:_start_tag_end(parts[name])] == root
    wb = load_workbook(path)
    assert wb["Cost Report"]["X9"].value == 3
    assert {p.name: p.value for p in wb.custom_doc_props.props}["k"] == "v"


def test_write_leaves_the_process_wide_namespace_registry_alone(tmp_path):
    from xml.etree import ElementTree as ET

    path = _book(tmp_path)
    before = dict(ET._namespace_map)
    writer.write(path, {"Cost Report": {"X9": 1}}, {"k": "v"})
    assert dict(ET._namespace_map) == before


def test_openpyxl_without_lxml_keeps_its_core_prefix_after_the_writer_is_imported(tmp_path):
    code = (
        "import sys, zipfile\n"
        "from estimating_tools.exchange import writer\n"
        "from openpyxl import Workbook\n"
        "p = sys.argv[1]\n"
        "Workbook().save(p)\n"
        "core = zipfile.ZipFile(p).read('docProps/core.xml')\n"
        "assert b'<cp:coreProperties' in core, core[:200]\n"
    )
    env = dict(os.environ, OPENPYXL_LXML="False")
    env.pop("PYTHONPATH", None)
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path / "c.xlsx")], env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_an_x_prefixed_sheet_writes_and_reads_back(tmp_path):
    path = _book(tmp_path)
    head = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<x:worksheet xmlns:x="{writer.NS}">')
    body = ('<x:sheetData><x:row r="1"><x:c r="A1" t="inlineStr"><x:is><x:t>keep'
            '</x:t></x:is></x:c></x:row></x:sheetData></x:worksheet>')
    writer._rewrite(path, {"xl/worksheets/sheet1.xml": (head + body).encode("utf-8")})
    writer.write_cells(path, {"Cost Report": {"B1": 7}})
    out = _entries(path)["xl/worksheets/sheet1.xml"]
    assert out.startswith(head.encode("utf-8")) and b'<x:c r="B1"><x:v>7</x:v></x:c>' in out
    assert load_workbook(path)["Cost Report"]["B1"].value == 7


def _refused(path, cells, text):
    before = path.read_bytes()
    try:
        writer.write_cells(path, cells)
    except ValueError as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert path.read_bytes() == before


def test_refusals_leave_the_file_untouched(tmp_path):
    path = _book(tmp_path)
    _refused(path, {"Cost Report": {"X9": math.nan}}, "Cost Report!X9 is nan")
    _refused(path, {"Cost Report": {"X9": math.inf}}, "only finite numbers")
    _refused(path, {"Cost Report": {"X9": "a\x00b"}}, "Cost Report!X9 holds a character")
    _refused(path, {"Cost Report": {"X9": Decimal("1.5")}}, "cannot write a Decimal")
    _refused(path, {"Cost Report": {"XFE1": 1}}, "Cost Report!XFE1")
    _refused(path, {"Cost Report": {"A1048577": 1}}, "Cost Report!A1048577")
    _refused(path, {"Cost Report": {"not a ref": 1}}, "Cost Report!not a ref")


def test_a_row_without_r_is_refused_by_name(tmp_path):
    path = _book(tmp_path)
    sheet = _entries(path)["xl/worksheets/sheet1.xml"]
    writer._rewrite(path, {"xl/worksheets/sheet1.xml": sheet.replace(b'<row r="1"', b"<row", 1)})
    _refused(path, {"Cost Report": {"X9": 1}}, "a row has no valid r")


def test_a_chartsheet_is_refused(tmp_path):
    path = _book(tmp_path)
    chart = b'<?xml version="1.0"?><chartsheet xmlns="' + writer.NS.encode() + b'"/>'
    writer._rewrite(path, {"xl/worksheets/sheet2.xml": chart})
    _refused(path, {"Notes": {"A1": 1}}, "Notes is not a worksheet")


def test_a_missing_custom_properties_part_is_refused(tmp_path):
    wb = Workbook()
    wb.active["A1"] = 1
    p = tmp_path / "plain.xlsx"
    wb.save(p)
    before = p.read_bytes()
    try:
        writer.set_custom_properties(p, {"k": "v"})
    except ValueError as exc:
        assert "no custom document properties part" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert p.read_bytes() == before


def test_write_patches_cells_and_properties_in_one_pass(tmp_path):
    path = _book(tmp_path)
    before = _entries(path)
    with zipfile.ZipFile(path) as z:
        order = z.namelist()
    n = writer.write(path, {"Cost Report": {"X9": 2}}, {"exported_at": "2026-11-03T00:00:00Z"})
    assert n == 1
    after = _entries(path)
    assert {k for k in before if before[k] != after[k]} == {
        "xl/worksheets/sheet1.xml", "docProps/custom.xml"}
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == order
    wb = load_workbook(path)
    assert wb["Cost Report"]["X9"].value == 2
    props = {p.name: p.value for p in wb.custom_doc_props.props}
    assert props["exported_at"] == "2026-11-03T00:00:00Z"


def _ns_sheet(root_decls, row_attrs):
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<ns0:worksheet xmlns:ns0="{writer.NS}"{root_decls}><ns0:sheetData>'
            f'<ns0:row r="1"{row_attrs}/></ns0:sheetData></ns0:worksheet>').encode("utf-8")


def test_ns_n_prefixes_are_never_silently_rebound(tmp_path):
    from xml.etree import ElementTree as ET

    path = _book(tmp_path)
    # Repro: the row declares its own prefix; ElementTree would invent ns1, which
    # the head already binds to another URI. Refused or resolved, never wrong.
    sheet = _ns_sheet(' xmlns:ns1="urn:other"', ' xmlns:q="urn:x14" q:dy="1"')
    writer._rewrite(path, {"xl/worksheets/sheet1.xml": sheet})
    try:
        writer.write_cells(path, {"Cost Report": {"B1": 1}})
    except ValueError as exc:
        assert "would rebind prefix 'ns1'" in str(exc)
    else:
        out = _entries(path)["xl/worksheets/sheet1.xml"]
        row = ET.fromstring(out).find(f".//{{{writer.NS}}}row")
        assert row.get("{urn:x14}dy") == "1"


def test_ns_n_source_prefixes_are_bound_directly(tmp_path):
    from xml.etree import ElementTree as ET

    path = _book(tmp_path)
    sheet = _ns_sheet(' xmlns:ns1="urn:x14"', ' ns1:dy="1"')
    writer._rewrite(path, {"xl/worksheets/sheet1.xml": sheet})
    before = dict(ET._namespace_map)
    writer.write_cells(path, {"Cost Report": {"B1": 1}})
    assert dict(ET._namespace_map) == before
    out = _entries(path)["xl/worksheets/sheet1.xml"]
    assert out.startswith(sheet[:sheet.index(b"<ns0:sheetData>")])
    row = ET.fromstring(out).find(f".//{{{writer.NS}}}row")
    assert row.get("{urn:x14}dy") == "1" and b'<ns0:c r="B1"><ns0:v>1</ns0:v></ns0:c>' in out


def test_property_names_and_none_values_are_checked(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    for props, text in (({"k": None}, "custom property 'k' cannot be None"),
                        ({"a\x00b": "v"}, "holds a character XML cannot carry")):
        try:
            writer.set_custom_properties(path, props)
        except ValueError as exc:
            assert text in str(exc), str(exc)
        else:
            raise AssertionError("expected ValueError")
        assert path.read_bytes() == before


def test_a_formula_lands_in_an_empty_cell(tmp_path):
    path = _book(tmp_path)
    writer.write_cells(path, {"Cost Report": {"C3": writer.Formula("=SUM(A1:A3)"),
                                              "Y9": writer.Formula("=X9*2")}})
    ws = load_workbook(path)["Cost Report"]
    assert ws["C3"].value == "=SUM(A1:A3)" and ws["C3"].data_type == "f"
    assert ws["Y9"].value == "=X9*2" and ws["Y9"].data_type == "f"
    with zipfile.ZipFile(path) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>SUM(A1:A3)</f>" in xml and "<f>=" not in xml


def test_a_formula_over_a_formula_is_refused(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    try:
        writer.write_cells(path, {"Cost Report": {"B2": writer.Formula("=1")}})
    except ValueError as exc:
        assert "formula" in str(exc)
    else:
        raise AssertionError("a formula cell must not be overwritten")
    assert path.read_bytes() == before


def test_a_formula_without_equals_is_stored_as_given(tmp_path):
    path = _book(tmp_path)
    writer.write_cells(path, {"Cost Report": {"C3": writer.Formula("A1")}})
    assert load_workbook(path)["Cost Report"]["C3"].value == "=A1"


def test_a_formula_with_a_character_xml_cannot_carry_is_refused(tmp_path):
    path = _book(tmp_path)
    try:
        writer.write_cells(path, {"Cost Report": {"C3": writer.Formula("=\x01")}})
    except ValueError:
        pass
    else:
        raise AssertionError("a control character must be refused")


def _calc_pr(path):
    import re
    with zipfile.ZipFile(path) as z:
        xml = z.read("xl/workbook.xml").decode()
    return re.findall(r"<calcPr[^>]*>", xml), xml


def _without_calc_pr(path, ext_lst=False):
    """Rewrite ``path``'s workbook.xml with no ``<calcPr>`` (and, with
    ``ext_lst``, an ``<extLst/>`` as its last child)."""
    import re
    parts = _entries(path)
    xml = re.sub(rb"<calcPr[^>]*/>", b"", parts["xl/workbook.xml"])
    if ext_lst:
        xml = xml.replace(b"</workbook>", b"<extLst/></workbook>")
        assert b"<extLst/>" in xml
    parts["xl/workbook.xml"] = xml
    with zipfile.ZipFile(path, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)


@pytest.mark.parametrize("ext_lst", [False, True])
def test_full_calc_on_load_is_added_where_calc_pr_is_missing(tmp_path, ext_lst):
    path = _book(tmp_path)
    _without_calc_pr(path, ext_lst)
    assert _calc_pr(path)[0] == []
    writer.write(path, cells={"Cost Report": {"Y9": "x"}}, full_calc_on_load=True)
    found, xml = _calc_pr(path)
    assert len(found) == 1 and 'fullCalcOnLoad="1"' in found[0]
    # Schema position: after definedNames/sheets, before anything that follows calcPr.
    assert xml.index("<calcPr") > xml.index("<sheets")
    if ext_lst:   # extLst must follow calcPr
        assert xml.index("<calcPr") < xml.index("<extLst")
    assert load_workbook(path)["Cost Report"]["Y9"].value == "x"   # well-formed, reloads


def test_full_calc_on_load_sets_an_existing_calc_pr(tmp_path):
    path = _book(tmp_path)
    parts = _entries(path)
    xml = parts["xl/workbook.xml"].replace(b'fullCalcOnLoad="1"', b"")
    with zipfile.ZipFile(path, "w") as z:
        for name, data in {**parts, "xl/workbook.xml": xml}.items():
            z.writestr(name, data)
    assert "fullCalcOnLoad" not in _calc_pr(path)[0][0]
    writer.write(path, properties={"exported_at": "x"}, full_calc_on_load=True)
    (calc,), _xml = _calc_pr(path)
    assert 'fullCalcOnLoad="1"' in calc and 'calcId="' in calc
    load_workbook(path)


def test_without_full_calc_the_workbook_part_is_untouched(tmp_path):
    path = _book(tmp_path)
    _without_calc_pr(path)
    before = _entries(path)["xl/workbook.xml"]
    writer.write(path, cells={"Cost Report": {"Y9": "x"}})
    assert _entries(path)["xl/workbook.xml"] == before
