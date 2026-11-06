"""A layout-2 book (built by 0.1.95 or 0.1.96, before the exchange stamp)
upgrades in memory to the stamp and keeps reading, applying and patching
(``heavybook.legacy``).

The fixtures ``fixtures/layout2-book.xlsx`` and ``fixtures/layout2-page.xlsx``
were built once with the code of the 0.1.96 release (commit ``391233f1``,
``git archive 391233f1 packages/estimating-tools`` extracted and put on
``PYTHONPATH``) and are never regenerated:

- ``layout2-book.xlsx``: ``heavybook.build.build(doc, style=style.load_style(),
  exported_at="2026-10-20T09:00:00Z", host="www.bidsheet.ai")`` then
  ``build.save``, where ``doc`` is the golden payload ``fixtures/workbook.json``;
- ``layout2-page.xlsx``: the same call on the golden payload reduced to its
  first item (id 1) exactly as ``exchange/tests/test_stamp.py::_page_doc``
  reduces it -- ``items`` to that item, ``activities`` to the item's,
  ``resources`` to those activities', ``shares`` to the item's, ``elements``
  to those whose quantities pay that item or none -- without the ``_fetch``
  record, which 0.1.96 did not know.

Both carry the old layout document in ``_wb!A1`` (``layout_version: 2``,
``format: heavybook``, a top-level ``baseline``) and the custom document
properties ``bidsheet_host`` and ``exported_at``.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from estimating_tools.estimate_spec import cli
from estimating_tools.exchange import client, registry
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.facts import read_facts
from estimating_tools.exchange.types import ApplyResult
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CR
from estimating_tools.exchange.reader import ReadRefused
from estimating_tools.exchange.reader import book as reader_book
from estimating_tools.heavybook.tests import _readback as H

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_ITEM = 1


@pytest.fixture(autouse=True)
def packs(monkeypatch, tmp_path):
    """What ``exchange/tests/test_cli.py`` does: the two packs registered and
    a stub token stored for the fixture's host."""
    from estimating_tools.estimate_spec import pack as fb_pack
    monkeypatch.setattr(registry, "discover",
                        lambda: registry.Discovery([fb_pack.pack(), hb_pack.pack()], []))
    monkeypatch.setenv("ESTIMATING_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    client.login("https://www.bidsheet.ai", "tok")


def _copy(tmp_path, name="layout2-book.xlsx"):
    path = tmp_path / name
    shutil.copy(FIXTURES / name, path)
    return path


def _edit_item_quantity(path, value=123):
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'ITEM', 1)}"] = value
    H.save_book(wb, path)


def _edit_resource_quantity(path):
    """``test_cli.py::_edited_book``'s edit: resource 1's quantity to 31."""
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 1)
    ws[f"{CR.QTY}{row}"] = 31
    H.save_book(wb, path)
    return row


def _applied():
    """The fixture payload after ``_edit_resource_quantity`` was applied."""
    fresh = H.fixture_doc()
    for r in fresh["resources"]:
        if r["id"] == 1:
            r["quantity"] = "31.000"
            r["v"] = "0123456789abcdef"
    return fresh


def _plan(eid, ops, *, dry_run=True, request_id=None, host=None):
    return ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {},
                                  "request_id": request_id or "r"}, dry_run=dry_run)


def _parts(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _sheet_part(parts, title):
    """The worksheet part of the sheet titled ``title``."""
    workbook = parts["xl/workbook.xml"].decode("utf-8")
    rid = re.search(rf'<sheet[^>]*name="{re.escape(title)}"[^>]*r:id="([^"]+)"', workbook)
    if rid is None:  # attribute order varies by writer
        rid = re.search(rf'<sheet[^>]*r:id="([^"]+)"[^>]*name="{re.escape(title)}"', workbook)
    rels = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    target = re.search(rf'<Relationship[^>]*Id="{rid.group(1)}"[^>]*Target="([^"]+)"', rels)
    if target is None:
        target = re.search(rf'<Relationship[^>]*Target="([^"]+)"[^>]*Id="{rid.group(1)}"', rels)
    return "xl/" + target.group(1).lstrip("/").removeprefix("xl/")


def _stamp(path) -> exchange_stamp.Stamp:
    return exchange_stamp.parse(json.loads(H.open_book(path)["_wb"]["A1"].value))


def _load(path):
    """The generic loader with the HeavyBook pack: a layout-2 book upgrades
    through the pack's ``upgrade_stamp``."""
    return reader_book.load(path, pack=hb_pack.pack())


def test_a_layout2_book_reads_to_the_same_change_set(tmp_path):
    old = _copy(tmp_path)
    _edit_item_quantity(old)
    new = H.build_book(H.fixture_doc(), tmp_path / "layout3.xlsx")
    _edit_item_quantity(new)
    p = hb_pack.pack()
    old_result, new_result = p.read(old), p.read(new)
    assert not old_result.refused, old_result.problems
    assert not new_result.refused, new_result.problems
    assert old_result.change_set.ops == new_result.change_set.ops
    assert old_result.change_set.ops  # the edit was seen


def test_a_layout2_book_detects_ok_and_loads_an_upgraded_stamp(tmp_path):
    path = _copy(tmp_path)
    assert hb_pack.pack().detect(read_facts(path)) == "ok"
    book = _load(path)
    st = book.stamp
    assert st.extra["upgraded_from"] == 2
    assert st.pack["name"] == "heavybook"
    assert st.host == "www.bidsheet.ai"
    assert st.exported_at == "2026-10-20T09:00:00Z"
    assert st.extra["layout"]["layout_version"] == 3
    assert "baseline" not in st.extra["layout"] and "format" not in st.extra["layout"]
    assert st.estimate_id == 1 and st.estimate_v == book.doc["estimate"]["v"]
    assert book.decl is not None
    # A layout-2 book's owner tags are stored constants, and its Crews sheet
    # has no crew-row helper: the upgraded declaration says so.
    assert book.decl.sheets["cost_report"].tags["parent"].derived == ()
    assert book.decl.sheets["crews"].tags["parent"].derived == ()
    assert "owner_row" not in book.decl.sheets["crews"].tags
    assert "*" not in book.decl.sheets["crews"].formulas
    assert book.doc == H.fixture_doc()
    assert book.tab("cost_report") == "Cost Report"


def test_a_layout2_book_applies_and_is_patched_to_layout3(monkeypatch, tmp_path, capsys):
    path = _copy(tmp_path)
    row = _edit_resource_quantity(path)
    before = _parts(path)
    fresh = _applied()
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: fresh)
    assert cli.main(["apply", str(path), "--commit"]) == 0
    assert "tagged" in capsys.readouterr().out
    st = _stamp(path)
    assert st.extra["upgraded_from"] == 2
    assert st.extra["layout"]["layout_version"] == 3
    assert st.pack["name"] == "heavybook" and st.host == "www.bidsheet.ai"
    assert st.exported_at != "2026-10-20T09:00:00Z"
    wb = H.open_book(path)
    assert wb[H.CR_TAB][f"{CR.V}{row}"].value == "0123456789abcdef"
    result = hb_pack.pack().read(path)
    assert not result.refused, result.problems
    assert result.change_set.ops == []
    after = _parts(path)
    assert set(before) == set(after)
    changed = H.changed_beyond_cached_values(before, after)
    # The stamp, the patched rows, the Checks sheet's export line (#426).
    allowed = {_sheet_part(before, "_wb"), _sheet_part(before, H.CR_TAB),
               _sheet_part(before, "Checks"), "docProps/custom.xml", "xl/workbook.xml"}
    assert changed <= allowed, changed - allowed


def test_a_layout2_page_book_stays_a_page(tmp_path):
    path = _copy(tmp_path, "layout2-page.xlsx")
    book = _load(path)
    assert book.stamp.page is True
    assert book.stamp.item_ids == [PAGE_ITEM]
    assert book.stamp.extra["upgraded_from"] == 2
    assert exchange_stamp.covered(path) == (True, [PAGE_ITEM])


def test_a_layout1_book_is_still_refused(tmp_path):
    path = _copy(tmp_path)
    wb = H.open_book(path)
    doc = json.loads(wb["_wb"]["A1"].value)
    wb["_wb"]["A1"] = json.dumps(dict(doc, layout_version=1))
    H.save_book(wb, path)
    with pytest.raises(ReadRefused) as exc:
        _load(path)
    assert "layout 1" in str(exc.value) and "rebuild the book" in str(exc.value)
    assert hb_pack.pack().detect(read_facts(path)) == "ok"


def test_a_layout2_host_property_holding_an_origin_upgrades_to_the_bare_host(tmp_path):
    """An older build may have stamped the property as an https origin; the
    upgraded stamp carries the bare host the build writes today."""
    path = _copy(tmp_path)
    wb = H.open_book(path)
    for prop in wb.custom_doc_props.props:
        if prop.name == "bidsheet_host":
            prop.value = "https://www.bidsheet.ai"
    H.save_book(wb, path)
    book = _load(path)
    assert book.stamp.host == "www.bidsheet.ai"
    assert book.stamp.extra["upgraded_from"] == 2


def test_a_layout2_book_without_a_host_is_refused(tmp_path):
    path = _copy(tmp_path)
    wb = H.open_book(path)
    wb.custom_doc_props.props = [p for p in wb.custom_doc_props.props
                                 if p.name != "bidsheet_host"]
    H.save_book(wb, path)
    result = hb_pack.pack().read(path)
    assert result.refused
    assert any("names no BidSheet.ai host" in p and "rebuild the book" in p
               for p in result.problems), result.problems


@pytest.mark.parametrize("foreign", [False, True], ids=["copied", "pasted-from-another-book"])
def test_a_resource_pasted_into_another_activity_of_a_layout2_book_is_a_create(tmp_path, foreign):
    """Insert Copied Cells of activity 2's resource 3 into activity 1: its
    stored owner tag still names activity 2 (a layout-2 book derives none),
    so the row is classified by where it sits, the stored ids only hinting
    where it came from -- as on any book."""
    path = _copy(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    src = H.cr_row(ws, "RESOURCE", 3)
    new = H.insert_copies(ws, src, src, H.block_end(ws, 1))
    assert ws[f"{CR.PARENT}{new}"].value == 2
    if foreign:
        ws[f"{CR.ID}{new}"] = 9999
        ws[f"{CR.PARENT}{new}"] = 8888
        ws[f"{CR.V}{new}"] = "0123456789abcdef"
    H.save_book(wb, path)
    result = hb_pack.pack().read(path)
    assert not result.refused, result.problems
    (op,) = result.change_set.ops
    assert op["op"] == "resource.create" and op["fields"]["activity_id"] == 1
