"""HeavyBook's declaration is generated from ``columns.py`` and its own
tables; the shipped ``pack.yaml`` equals it (spec, Testing: declaration
drift), and it says what the layout and the scanner say."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from estimating_tools.exchange import declaration as D, stamp as exchange_stamp
from estimating_tools.heavybook import declaration as HD
from estimating_tools.heavybook import layout
from estimating_tools.heavybook.tests import _readback as H

SHIPPED = Path(HD.__file__).with_name("pack.yaml")


def test_the_shipped_declaration_has_not_drifted():
    got = HD.generate()
    if os.environ.get("UPDATE_GOLDEN") == "1":
        SHIPPED.write_text(HD.dumps(got), encoding="utf-8", newline="\n")
    assert yaml.safe_load(SHIPPED.read_text(encoding="utf-8")) == got, (
        "heavybook/pack.yaml is stale: regenerate with UPDATE_GOLDEN=1 pytest "
        "heavybook/tests/test_declaration.py")


def test_the_generated_declaration_loads():
    decl = D.load(HD.generate())
    assert decl.pack.name == "heavybook" and decl.kind == "code"
    assert decl.prototypes == layout.TEMPLATE_NAMES
    assert decl.size() < 12000


def test_row_kinds_equal_the_layouts():
    """The declaration's row kinds are ``layout._row_kinds()`` in the generic
    tag names (id, v, parent, key, name)."""
    want = {}
    rename = {"element_id": "id", "quantity_key": "key", "parent_id": "parent",
              "activity_id": "parent", "crew_id": "parent"}
    for entry in layout._row_kinds():
        sheet = want.setdefault(entry["sheet"], {"kind_cell": entry["kind_cell"], "kinds": {}})
        sheet["kinds"][entry["kind"]] = {rename.get(k, k): v
                                        for k, v in entry["identified_by"].items()}
    assert D.load(HD.generate()).row_kinds() == want


def test_the_built_book_carries_a_loadable_declaration(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
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
    assert HD.DERIVED is layout.DERIVED
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
