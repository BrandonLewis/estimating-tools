"""``writer.edit(names=...)`` sets workbook-scoped defined names, and
``properties=`` creates the custom-properties part a book saved without one
lacks -- what a template fill needs to stamp a book an author saved in
Excel."""
from __future__ import annotations

import zipfile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.workbook.defined_name import DefinedName

from estimating_tools.exchange import writer


def _plain(tmp_path):
    wb = Workbook()
    wb.active["A1"] = "x"
    wb.create_sheet("_wb")
    wb.defined_names["kept"] = DefinedName("kept", attr_text="Sheet!$A$1")
    path = tmp_path / "plain.xlsx"
    wb.save(path)
    return path


def test_a_book_without_custom_properties_gets_the_part(tmp_path):
    path = _plain(tmp_path)
    assert "docProps/custom.xml" not in zipfile.ZipFile(path).namelist()
    writer.edit(path, properties={"estimate_format": "demo 1"})
    wb = load_workbook(path)
    assert [(p.name, p.value) for p in wb.custom_doc_props.props] == [
        ("estimate_format", "demo 1")]
    writer.edit(path, properties={"estimate_format": "demo 2", "exported_at": "now"})
    wb = load_workbook(path)
    assert [(p.name, p.value) for p in wb.custom_doc_props.props] == [
        ("estimate_format", "demo 2"), ("exported_at", "now")]
    with zipfile.ZipFile(path) as z:
        assert z.read("[Content_Types].xml").count(b"/docProps/custom.xml") == 1
        assert z.read("_rels/.rels").count(b"docProps/custom.xml") == 1


def test_names_are_added_or_replaced(tmp_path):
    path = _plain(tmp_path)
    writer.edit(path, names={"exchange.stamp": "'_wb'!$A$1", "demo.total": "Sheet!$A$1"})
    writer.edit(path, names={"demo.total": "Sheet!$A$2"})
    names = {n: d.attr_text for n, d in load_workbook(path).defined_names.items()}
    assert names == {"kept": "Sheet!$A$1", "exchange.stamp": "'_wb'!$A$1",
                     "demo.total": "Sheet!$A$2"}


def test_names_match_whatever_their_case_as_excel_matches_them(tmp_path):
    """Excel's defined names are case-insensitive: ``demo.total`` replaces
    the book's ``DEMO.TOTAL`` (keeping its spelling), and two spellings in
    one edit are one name (the last one's text). openpyxl would fold a
    duplicate into one dict key, so the raw ``workbook.xml`` is read."""
    from xml.etree import ElementTree as ET

    path = _plain(tmp_path)
    writer.edit(path, names={"DEMO.TOTAL": "Sheet!$A$1"})
    writer.edit(path, names={"demo.total": "Sheet!$A$2", "x.a": "Sheet!$A$3",
                             "X.A": "Sheet!$A$4"})
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("xl/workbook.xml"))
    assert [(dn.get("name"), dn.text) for dn in root.iter(f"{{{writer.NS}}}definedName")] == [
        ("kept", "Sheet!$A$1"), ("DEMO.TOTAL", "Sheet!$A$2"), ("x.a", "Sheet!$A$4")]


@pytest.mark.parametrize("name, text", [
    ("A1", "Sheet!$A$1"), ("bad name", "Sheet!$A$1"), ("ok", ""), ("AB12", "Sheet!$A$1"),
    ("R", "Sheet!$A$1"), ("c", "Sheet!$A$1"), ("R2C3", "Sheet!$A$1"), ("r2c3", "Sheet!$A$1"),
    ("RC", "Sheet!$A$1"), ("R2", "Sheet!$A$1"), ("c3", "Sheet!$A$1"), ("R2C", "Sheet!$A$1"),
    ("x" * 256, "Sheet!$A$1")])
def test_a_name_excel_refuses_writes_nothing(tmp_path, name, text):
    path = _plain(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        writer.edit(path, names={name: text})
    assert path.read_bytes() == before


@pytest.mark.parametrize("name", ["Rate", "Cost", "R_2", "x" * 255, "hb.total"])
def test_names_near_the_refused_shapes_are_accepted(tmp_path, name):
    path = _plain(tmp_path)
    writer.edit(path, names={name: "Sheet!$A$1"})
    assert name in load_workbook(path).defined_names


def test_two_edits_of_one_book_write_the_same_bytes(tmp_path):
    a, b = _plain(tmp_path), tmp_path / "copy.xlsx"
    b.write_bytes(a.read_bytes())
    for path in (a, b):
        writer.edit(path, properties={"k": "v"}, names={"n": "Sheet!$A$1"})
    assert a.read_bytes() == b.read_bytes()
