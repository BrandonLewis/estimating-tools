"""The declaration a code-built (version 1) HeavyBook book carries, generated
from ``columns.py`` and its own tables (``heavybook.declaration.generate``,
what the legacy upgrades produce): it loads and says what the layout and the
scanner say. The version-2 pack's declaration is its template's
``pack.yaml``."""
from __future__ import annotations

import json
from pathlib import Path

from estimating_tools.exchange import declaration as D, stamp as exchange_stamp
from estimating_tools.heavybook import declaration as HD
from estimating_tools.heavybook import codebook
from estimating_tools.heavybook.tests import _readback as H

def test_the_generated_declaration_loads():
    decl = D.load(HD.generate())
    assert decl.pack.name == "heavybook" and decl.kind == "code"
    assert decl.prototypes == codebook.TEMPLATE_NAMES
    assert decl.size() < 12000


#: The row kinds the retired code build's layout declared
#: (``layout._row_kinds()``), in the generic tag names.
ROW_KINDS = {
    "cost_report": {"kind_cell": "W", "kinds": {
        "ITEM": {"id": "X", "v": "Y"}, "ELEMENT_QTY": {"id": "X", "key": "AD", "v": "Y"},
        "ACTIVITY": {"id": "X", "v": "Y", "parent": "Z"},
        "STEP": {"id": "X", "v": "Y", "parent": "Z"},
        "RESOURCE": {"id": "X", "v": "Y", "parent": "Z"},
        "STEPS": {"parent": "Z"}, "START": {"parent": "Z"}, "END": {"parent": "Z"},
        "GROUP": {}}},
    "crews": {"kind_cell": "K", "kinds": {
        "CREW": {"id": "L", "v": "M"}, "MEMBER": {"id": "L", "parent": "N"},
        "NOTE": {"parent": "N"}, "CREW_END": {"parent": "N"}}},
    "bid_form": {"kind_cell": "J", "kinds": {
        "ESTIMATE": {"id": "K", "v": "L", "name": "T"}, "BID_INPUT": {"name": "T"},
        "BID_FIGURE": {"name": "T"}, "SECTION": {"id": "K", "v": "L"},
        "ITEM_BID": {"id": "K", "v": "L"}, "BID_TOTAL": {"id": "K"}, "GROUP": {}}},
}


def test_row_kinds_equal_the_code_layouts():
    assert D.load(HD.generate()).row_kinds() == ROW_KINDS


def test_a_code_built_book_carries_a_loadable_declaration(tmp_path):
    import shutil

    path = tmp_path / "e1.xlsx"
    shutil.copy(Path(H.__file__).parent / "fixtures" / "v1-book.xlsx", path)
    st = exchange_stamp.read(path)
    decl = D.load(st.declaration)
    assert decl.sheets["cost_report"].tab == "Cost Report"
    assert st.schema == D.SCHEMA_VERSION
    # The stamp sorts keys; the declaration read back keeps the generator's
    # column order.
    assert decl.visible("cost_report") == tuple(HD.generate()["sheets"]["cost_report"]["columns"])
    assert decl.growable("cost_report") == ("ACTIVITY", "STEP", "RESOURCE")


def test_a_stamp_whose_declaration_does_not_load_is_refused(tmp_path):
    from openpyxl import load_workbook

    from estimating_tools.exchange.reader import ReadRefused, read_book
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    wb = load_workbook(path)
    doc = json.loads(wb["_wb"]["A1"].value)
    doc["declaration"]["schema"] = 9
    wb["_wb"]["A1"] = exchange_stamp.dumps(doc)
    wb.save(path)
    try:
        read_book(path)
    except ReadRefused as exc:
        msg = str(exc)
        assert "schema 9" in msg and "update the plugin" in msg
    else:
        raise AssertionError("not refused")


def test_every_pack_declares():
    from estimating_tools.estimate_spec import pack as fb
    from estimating_tools.heavybook import pack as hb
    for p in (hb.pack(), fb.pack()):
        decl = p.declaration()
        assert decl.pack.name == p.name and decl.pack.version == p.version


def test_the_declaration_says_which_tags_are_derived():
    decl = D.load(HD.generate())
    assert decl.sheets["cost_report"].tags["parent"].derived == (
        "STEP", "RESOURCE", "STEPS", "START", "END") == HD.DERIVED["cost_report"]
    assert decl.sheets["crews"].tags["parent"].derived == (
        "MEMBER", "NOTE", "CREW_END") == HD.DERIVED["crews"]
    assert HD.DERIVED is codebook.DERIVED
    # The helpers the derived tags read through: every row holds one.
    assert decl.sheets["cost_report"].tags["owner_row"].column == "AJ"
    assert decl.sheets["crews"].tags["owner_row"].column == "R"
    assert tuple(decl.sheets["cost_report"].formulas["*"]) == ("AJ",)
    assert tuple(decl.sheets["crews"].formulas["*"]) == ("R",)


def test_a_stored_tag_declaration_derives_nothing_and_has_no_crew_helper():
    """``generate(derived=False)``: a layout-2 book's declaration
    (``legacy.upgrade``) -- its cells hold stored tags and its Crews sheet
    has no helper column, so nothing is derived and no ``R`` formula is
    checked. Everything else is the current declaration's."""
    stored, current = HD.generate(derived=False), HD.generate()
    decl = D.load(stored)
    for key in ("cost_report", "crews"):
        assert decl.sheets[key].tags["parent"].derived == ()
        assert decl.sheets[key].tags["parent"].column == D.load(current).sheets[key].tag("parent")
    assert "owner_row" not in decl.sheets["crews"].tags
    assert "*" not in decl.sheets["crews"].formulas
    assert decl.sheets["cost_report"].tags["owner_row"].column == "AJ"
    assert tuple(decl.sheets["cost_report"].formulas["*"]) == ("AJ",)
    # Nothing else differs.
    stored["sheets"]["cost_report"]["tags"]["parent"]["derived"] = list(HD.DERIVED["cost_report"])
    stored["sheets"]["crews"]["tags"]["parent"]["derived"] = list(HD.DERIVED["crews"])
    stored["sheets"]["crews"]["tags"]["owner_row"] = "R"
    stored["sheets"]["crews"]["formulas"]["*"] = ["R"]
    assert stored == current
