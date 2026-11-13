"""A book built (or patched) by the step 2a code (#437) keeps reading and
applying: its schema-1 stamp carries a declaration that predates step 2b (no
``within`` on the activity block, no ``derived`` tags, no crew-row helper),
and its cells hold what that declaration says (stored owner tags, no chain
formulas, no Crews ``R`` column). ``HeavyBookPack.upgrade_stamp`` swaps in
``declaration.generate(tabs=..., derived=False)`` in memory, and the first
committed apply writes the upgraded stamp back.

The fixtures were built once with the code of the step 2a squash merge
(commit ``b2a0075c``: ``git archive b2a0075c packages/estimating-tools``
extracted and put on ``PYTHONPATH``, ``estimating_tools.__file__`` checked to
be the extraction's) and are never regenerated:

- ``step2a-book.xlsx``: ``heavybook.build.build(doc, style=style.load_style(),
  exported_at="2026-11-05T00:00:00Z", host="www.bidsheet.ai")`` then
  ``build.save``, where ``doc`` is the golden payload ``fixtures/workbook.json``;
- ``step2a-patched-layout2.xlsx``: a copy of ``layout2-book.xlsx`` edited and
  applied with that code's ``est-estimate apply --commit`` exactly as its
  ``test_legacy.py::test_a_layout2_book_applies_and_is_patched_to_layout3``
  does (resource 1's quantity to 31; ``client.apply`` stubbed to an empty
  plan, ``client.fetch`` to the golden payload with resource 1 at
  ``"31.000"``, ``v`` ``0123456789abcdef``; host ``www.bidsheet.ai``). Its
  patch wrote the step-2a stamp (``upgraded_from: 2``) with the patch time as
  ``exported_at`` (``2026-11-05T16:10:10Z``).

Both stamps say ``schema: 1`` and their activity block has no ``within``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from estimating_tools.estimate_spec import cli
from estimating_tools.exchange import client, registry
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.facts import read_facts
from estimating_tools.exchange.reader import book as reader_book
from estimating_tools.exchange.types import ApplyResult
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CR, CW
from estimating_tools.heavybook.tests import _readback as H

FIXTURES = Path(__file__).parent / "fixtures"
STEP2A = "step2a-book.xlsx"
PATCHED = "step2a-patched-layout2.xlsx"


@pytest.fixture(autouse=True)
def packs(monkeypatch, tmp_path):
    """``test_legacy.py``'s setup: the two packs registered and a stub token
    stored for the fixtures' host."""
    from estimating_tools.estimate_spec import pack as fb_pack
    monkeypatch.setattr(registry, "discover",
                        lambda: registry.Discovery([fb_pack.pack(), hb_pack.pack()], []))
    monkeypatch.setenv("ESTIMATING_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    client.login("https://www.bidsheet.ai", "tok")


def _copy(tmp_path, name=STEP2A):
    path = tmp_path / name
    shutil.copy(FIXTURES / name, path)
    return path


def _fresh(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "fresh.xlsx")


def _raw(path) -> dict:
    return json.loads(H.open_book(path)["_wb"]["A1"].value)


def _edit(path, fn, sheet=H.CR_TAB):
    wb = H.open_book(path)
    fn(wb[sheet])
    H.save_book(wb, path)


def _ops(path):
    result = hb_pack.pack().read(path)
    assert not result.refused, result.problems
    return result.change_set.ops


def test_the_fixtures_carry_a_step2a_stamp():
    for name in (STEP2A, PATCHED):
        raw = _raw(FIXTURES / name)
        assert raw["schema"] == 1
        assert "within" not in raw["declaration"]["sheets"]["cost_report"]["blocks"]["activity"]
    assert _raw(FIXTURES / PATCHED)["extra"]["upgraded_from"] == 2


def test_a_step2a_book_detects_ok_and_reads_clean(tmp_path):
    path = _copy(tmp_path)
    assert hb_pack.pack().detect(read_facts(path)) == "ok"
    assert _ops(path) == []
    book = reader_book.load(path, pack=hb_pack.pack())
    cost_report, crews = book.decl.sheets["cost_report"], book.decl.sheets["crews"]
    assert cost_report.blocks["activity"].within
    assert cost_report.tags["parent"].derived == ()
    assert crews.tags["parent"].derived == ()
    assert "owner_row" not in crews.tags
    assert "*" not in crews.formulas
    assert book.stamp.extra["upgraded_from"] == "2a"
    assert book.stamp.exported_at == "2026-11-05T00:00:00Z"
    H.assert_old_book_doc(book.doc)


def test_a_step2a_book_reads_an_edit_as_a_fresh_book_does(tmp_path):
    def edit(ws):
        ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = 31
    old, new = _copy(tmp_path), _fresh(tmp_path)
    _edit(old, edit)
    _edit(new, edit)
    ops = _ops(old)
    assert ops and ops == _ops(new)


def test_a_typed_resource_reads_on_a_step2a_book(tmp_path):
    def typed(ws):
        H.type_row(ws, H.block_end(ws, 5), {
            CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "Equipment"})
    old, new = _copy(tmp_path), _fresh(tmp_path)
    _edit(old, typed)
    _edit(new, typed)
    ops = _ops(old)
    assert [op["op"] for op in ops] == ["resource.create"]
    assert ops == _ops(new)


def test_a_deleted_member_reads_on_a_step2a_book(tmp_path):
    def gone(ws):
        ws.delete_rows(H.cw_row(ws, "MEMBER", 2))
    old, new = _copy(tmp_path), _fresh(tmp_path)
    _edit(old, gone, sheet=H.CW_TAB)
    _edit(new, gone, sheet=H.CW_TAB)
    ops = _ops(old)
    assert ops and ops == _ops(new)


def test_a_copied_resource_reads_on_a_step2a_book(tmp_path):
    """A resource row copied to another activity: its stored tag names the
    activity it came from, its position the one it now sits under."""
    def copy(ws):
        r = H.cr_row(ws, "RESOURCE", 1)
        new = H.insert_copies(ws, r, r, H.block_end(ws, 5))
        ws[f"{CR.QTY}{new}"] = 40
    path = _copy(tmp_path)
    _edit(path, copy)
    (op,) = _ops(path)
    assert op["op"] == "resource.create" and op["fields"]["activity_id"] == 5


def test_a_layout2_book_patched_by_step2a_reads_clean_and_keeps_its_origin(tmp_path):
    path = _copy(tmp_path, PATCHED)
    assert hb_pack.pack().detect(read_facts(path)) == "ok"
    assert _ops(path) == []
    book = reader_book.load(path, pack=hb_pack.pack())
    assert book.stamp.extra["upgraded_from"] == 2
    assert book.decl.sheets["cost_report"].blocks["activity"].within
    assert book.decl.sheets["cost_report"].tags["parent"].derived == ()


def _plan(eid, ops, *, dry_run=True, request_id=None, host=None):
    return ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {},
                                  "request_id": request_id or "r"}, dry_run=dry_run)


def test_a_step2a_book_applies_and_its_stamp_is_upgraded_once(monkeypatch, tmp_path, capsys):
    path = _copy(tmp_path)
    _edit(path, lambda ws: ws.__setitem__(f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}", 31))
    fresh = H.fixture_doc()
    for r in fresh["resources"]:
        if r["id"] == 1:
            r["quantity"], r["v"] = "31.000", "0123456789abcdef"
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: fresh)
    assert cli.main(["apply", str(path), "--commit"]) == 0
    assert "tagged" in capsys.readouterr().out
    raw = _raw(path)
    assert raw["schema"] == exchange_stamp.SCHEMA_VERSION
    activity = raw["declaration"]["sheets"]["cost_report"]["blocks"]["activity"]
    assert activity["within"]
    assert raw["declaration"]["sheets"]["cost_report"]["tags"]["parent"]["derived"] == []
    assert "owner_row" not in raw["declaration"]["sheets"]["crews"]["tags"]
    assert raw["extra"]["upgraded_from"] == "2a"
    # Upgraded once: the written stamp is current, so the pack leaves it be.
    wb = H.open_book(path)
    assert hb_pack.pack().upgrade_stamp(raw, wb) == raw
    assert _ops(path) == []


def test_a_current_stamp_is_returned_unchanged(tmp_path):
    path = _fresh(tmp_path)
    raw = _raw(path)
    wb = H.open_book(path)
    assert hb_pack.pack().upgrade_stamp(raw, wb) == raw


def test_a_step2a_book_refreshes_and_takes_the_current_stamp(tmp_path):
    path = _copy(tmp_path)
    fresh = H.fixture_doc()
    next(r for r in fresh["resources"] if r["id"] == 1).update(quantity="32.000", v="1" * 16)
    report = hb_pack.pack().refresh(path, fresh)
    assert report.clean and report.baseline_replaced
    raw = _raw(path)
    assert raw["extra"]["upgraded_from"] == "2a"
    assert "within" in raw["declaration"]["sheets"]["cost_report"]["blocks"]["activity"]
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 32
    assert _ops(path) == []
