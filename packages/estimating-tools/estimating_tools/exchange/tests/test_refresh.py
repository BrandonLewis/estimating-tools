"""Refresh (engine spec, "Refresh"; "Testing": server-only change patched,
estimator-only change kept, both-sides change reported and not written,
server-added row inserted at block end with tags, baseline untouched when
anything was reported), through the HeavyBook pack, the oracle."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from estimating_tools.exchange import baseline as ex_baseline
from estimating_tools.exchange import writer
from estimating_tools.exchange.reader.book import STALE_PROPERTY
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CR, CW, RT
from estimating_tools.heavybook.tests import _readback as H


def _book(tmp_path, edit=None, name="e1.xlsx"):
    """The fixture book, with ``edit(wb)`` applied the way Excel would."""
    path = H.build_book(H.fixture_doc(), tmp_path / name)
    if edit is not None:
        wb = H.open_book(path)
        edit(wb)
        H.save_book(wb, path)
    return path


def _qty(resource_id, value):
    def edit(wb):
        ws = wb[H.CR_TAB]
        ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', resource_id)}"] = value
    return edit


def _fresh(changes):
    """The fixture payload with resources changed on the server:
    ``{resource id: {field: value}}``, each with a new ``v``."""
    doc = H.fixture_doc()
    for res in doc["resources"]:
        if res["id"] in changes:
            res.update(changes[res["id"]])
            res["v"] = f"{res['id']:016x}"
    return doc


def _read(path):
    result = hb_pack.pack().read(path)
    assert not result.problems, result.problems
    return result.change_set


def _baseline(path):
    ws = H.open_book(path)["_wb"]
    stamp = json.loads(ws["A1"].value)
    chunks = [ws.cell(row=r, column=2).value for r in range(1, stamp["baseline"]["chunks"] + 1)]
    return ex_baseline.decode(chunks, stamp["baseline"])


def test_a_server_only_change_is_written_and_the_baseline_replaced(tmp_path):
    path = _book(tmp_path)
    fresh = _fresh({1: {"quantity": "32.000"}})
    report = hb_pack.pack().refresh(path, fresh)
    assert report.clean and report.baseline_replaced and not report.dry_run
    ws = H.open_book(path)[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 1)
    assert ws[f"{CR.QTY}{row}"].value == 32
    assert ws[f"{CR.V}{row}"].value == f"{1:016x}"
    assert _baseline(path) == fresh
    assert _read(path).ops == []
    assert any("32" in line for line in report.written)


def test_an_estimator_only_change_is_kept(tmp_path):
    path = _book(tmp_path, _qty(2, 3))
    report = hb_pack.pack().refresh(path, _fresh({1: {"quantity": "32.000"}}))
    assert report.clean
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 2)}"].value == 3
    (op,) = _read(path).ops
    assert op["op"] == "resource.update" and op["ref"] == 2 and op["fields"] == {"quantity": "3"}


def test_a_change_on_both_sides_is_reported_and_nothing_written(tmp_path):
    path = _book(tmp_path, _qty(1, 31))
    before = path.read_bytes()
    report = hb_pack.pack().refresh(path, _fresh({1: {"quantity": "32.000"}}))
    assert not report.clean and not report.baseline_replaced
    (collision,) = report.collisions
    text = str(collision)
    assert "BidSheet.ai 32" in text and "this book 31" in text and "built with 30" in text
    assert text.startswith(f"{H.CR_TAB} row ")
    assert path.read_bytes() == before                  # the baseline untouched, and all else
    assert "nothing written" in report.text()


def test_both_sides_making_the_same_change_is_not_a_collision(tmp_path):
    path = _book(tmp_path, _qty(1, 32))
    report = hb_pack.pack().refresh(path, _fresh({1: {"quantity": "32.000"}}))
    assert report.clean and report.baseline_replaced
    assert _read(path).ops == []


def _added_resource(doc):
    """Resource 10, a material line, added on the server to activity 2."""
    res = dict(next(r for r in doc["resources"] if r["id"] == 2))
    res.update({"id": 10, "name": "Gravel", "component_type": "material", "quantity": "2.000",
                "unit_cost": "10.00", "labor_rate_id": None, "sort_order": 5,
                "v": "aaaaaaaaaaaaaaaa", "cost": "20.00"})
    doc["resources"].append(res)
    return doc


def test_a_server_added_row_is_inserted_at_its_block_end_with_its_tags(tmp_path):
    path = _book(tmp_path)
    end = H.cr_row(H.open_book(path)[H.CR_TAB], "END", parent=2)
    report = hb_pack.pack().refresh(path, _added_resource(H.fixture_doc()))
    assert report.clean and report.rows_added == 1
    ws = H.open_book(path)[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 10)
    assert row == end and ws[f"{CR.KIND}{end + 1}"].value == "END"
    assert ws[f"{CR.KIND}{row}"].value == "RESOURCE"
    assert ws[f"{CR.V}{row}"].value == "aaaaaaaaaaaaaaaa"
    assert ws[f"{CR.DESC}{row}"].value == "Gravel" and ws[f"{CR.TYPE}{row}"].value == "material"
    assert ws[f"{CR.PARENT}{row}"].value == H.owner_formula(row)
    assert str(ws[f"{CR.TOTAL}{row}"].value).startswith("=")
    assert _read(path).ops == []


def test_a_server_deleted_row_is_removed(tmp_path):
    path = _book(tmp_path)
    fresh = H.fixture_doc()
    fresh["resources"] = [r for r in fresh["resources"] if r["id"] != 3]
    report = hb_pack.pack().refresh(path, fresh)
    assert report.clean and report.rows_removed == 1
    ws = H.open_book(path)[H.CR_TAB]
    with pytest.raises(LookupError):
        H.cr_row(ws, "RESOURCE", 3)
    assert _read(path).ops == []
    # The Foreman's Checks and Flat rows are display rows: blanked, with a note.
    assert [n for n in report.notes if "no longer has are blanked" in n] == [
        "Checks: 1 resource row(s) BidSheet.ai no longer has are blanked; a rebuild removes them",
        "Flat: 1 resource row(s) BidSheet.ai no longer has are blanked; a rebuild removes them"]


def test_a_server_deleted_row_of_a_code_built_book_leaves_its_checks_row_reading_ref(
        tmp_path):
    import shutil

    path = tmp_path / "v1.xlsx"
    shutil.copy(Path(H.__file__).parent / "fixtures" / "v1-book.xlsx", path)
    fresh = H.fixture_doc()
    fresh["resources"] = [r for r in fresh["resources"] if r["id"] != 3]
    report = hb_pack.pack().refresh(path, fresh)
    assert report.clean and report.rows_removed == 1
    # The Foreman's Checks row pointed at its row: it reads #REF! (a note).
    assert any("#REF!" in n for n in report.notes)


def test_a_server_deleted_row_the_estimator_edited_is_a_collision(tmp_path):
    path = _book(tmp_path, _qty(3, 4))
    before = path.read_bytes()
    fresh = H.fixture_doc()
    fresh["resources"] = [r for r in fresh["resources"] if r["id"] != 3]
    report = hb_pack.pack().refresh(path, fresh)
    (collision,) = report.collisions
    assert "deleted in BidSheet.ai, edited in this book" in str(collision)
    assert path.read_bytes() == before


def test_an_item_added_on_the_server_needs_a_rebuild(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    fresh = H.fixture_doc()
    item = dict(fresh["items"][0])
    item.update({"id": 6, "item_number": "Z9", "description": "Added on the server"})
    fresh["items"].append(item)
    report = hb_pack.pack().refresh(path, fresh)
    assert not report.clean and not report.collisions
    assert "Added on the server" in report.structural[0]
    assert report.structural[0].endswith("rebuild it from BidSheet.ai")
    assert path.read_bytes() == before


def test_an_activitys_crew_changed_on_the_server_needs_a_rebuild(tmp_path):
    path = _book(tmp_path)
    fresh = H.fixture_doc()
    act = next(a for a in fresh["activities"] if a["id"] == 1)
    act.update({"crew_id": 2, "v": "bbbbbbbbbbbbbbbb"})
    report = hb_pack.pack().refresh(path, fresh)
    assert any("crew_id" in s for s in report.structural)


def test_a_dry_run_writes_nothing(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    report = hb_pack.pack().refresh(path, _fresh({1: {"quantity": "32.000"}}), dry_run=True)
    assert report.clean and report.dry_run and not report.baseline_replaced
    assert report.cells_written > 0 and "dry run" in report.text()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.patching.xlsx"))


def test_a_current_book_is_left_alone(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    report = hb_pack.pack().refresh(path, H.fixture_doc())
    assert report.current and "current" in report.text()
    assert path.read_bytes() == before


def test_a_crew_roster_replaced_on_the_server_replaces_the_rows(tmp_path):
    path = _book(tmp_path)
    fresh = H.fixture_doc()
    crew = next(c for c in fresh["crews"] if c["id"] == 1)
    for m, new_id in zip(crew["members"], (11, 12)):
        m["id"] = new_id
    crew["v"] = "cccccccccccccccc"
    report = hb_pack.pack().refresh(path, fresh)
    assert report.clean and report.rows_added == 2 and report.rows_removed == 2
    ws = H.open_book(path)[H.CW_TAB]
    assert [ws[f"{CW.ID}{r}"].value for r in (6, 7)] == [11, 12]
    assert ws[f"{CW.CODE}{7}"].value == "OPER" and ws[f"{CW.RATE_ID}{7}"].value == 1
    assert ws[f"{CW.EXPORT}{7}"].value == 54
    assert ws[f"{CW.KIND}{8}"].value == "CREW_END"
    assert _read(path).ops == []


def test_a_library_rate_change_reaches_the_rates_sheet_and_the_member(tmp_path):
    path = _book(tmp_path)
    fresh = H.fixture_doc()
    fresh["rates"]["labor"][0]["rate"] = "60.00"
    crew = next(c for c in fresh["crews"] if c["id"] == 1)
    next(m for m in crew["members"] if m["id"] == 2)["effective_hourly_rate"] = "60.00"
    report = hb_pack.pack().refresh(path, fresh)
    assert report.clean
    wb = H.open_book(path)
    rates = wb[H.RT_TAB]
    assert any(rates[f"{RT.RATE}{r}"].value == 60 for r in range(1, rates.max_row + 1))
    assert wb[H.CW_TAB][f"{CW.EXPORT}{H.cw_row(wb[H.CW_TAB], 'MEMBER', 2)}"].value == 60
    assert _read(path).ops == []


def test_a_stale_book_is_refused(tmp_path):
    path = _book(tmp_path)
    writer.set_custom_properties(path, {STALE_PROPERTY: "applied r1; patch not verified"})
    with pytest.raises(ValueError, match="could not be patched fully"):
        hb_pack.pack().refresh(path, _fresh({1: {"quantity": "32.000"}}))


def test_a_book_with_read_problems_is_refused(tmp_path):
    def typed_on_marker(wb):
        ws = wb[H.CR_TAB]
        ws[f"{CR.QTY}{H.cr_row(ws, 'END', parent=2)}"] = 5
    path = _book(tmp_path, typed_on_marker)
    with pytest.raises(ValueError, match="fix the book first"):
        hb_pack.pack().refresh(path, _fresh({1: {"quantity": "32.000"}}))


def test_the_refreshed_book_prices_like_a_fresh_build(tmp_path):
    from estimating_tools.estimate_spec.tests._formula_eval import evaluate

    path = _book(tmp_path)
    fresh = _added_resource(_fresh({1: {"quantity": "32.000"}}))
    # An item's bid quantity changed in BidSheet.ai: shown on the Bid Form
    # and hidden on the item's Cost Report row (AF), which its effective
    # quantity and unit price read.
    next(i for i in fresh["items"] if i["id"] == 2)["schedule_quantity"] = "40.00"
    assert hb_pack.pack().refresh(path, fresh).clean
    rebuilt = H.build_book(fresh, tmp_path / "rebuilt.xlsx")
    ours, theirs = H.open_book(path), H.open_book(rebuilt)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ev_ours, ev_theirs = evaluate(ours, tmp_path / "a"), evaluate(theirs, tmp_path / "b")
    for activity in (1, 2):
        r1 = H.cr_row(ours[H.CR_TAB], "ACTIVITY", activity)
        r2 = H.cr_row(theirs[H.CR_TAB], "ACTIVITY", activity)
        for col in "LMNOPQR":
            assert ev_ours[f"{H.CR_TAB}!{col}{r1}"] == pytest.approx(
                ev_theirs[f"{H.CR_TAB}!{col}{r2}"]), (activity, col)
    for item in fresh["items"]:
        r1 = H.cr_row(ours[H.CR_TAB], "ITEM", item["id"])
        r2 = H.cr_row(theirs[H.CR_TAB], "ITEM", item["id"])
        for col in (CR.H1, CR.H2, CR.H4, CR.TOTAL):
            assert ev_ours[f"{H.CR_TAB}!{col}{r1}"] == pytest.approx(
                ev_theirs[f"{H.CR_TAB}!{col}{r2}"]), (item["id"], col)


def test_fieldbook_cannot_refresh_yet(tmp_path):
    from estimating_tools.estimate_spec import pack as fb_pack
    from estimating_tools.exchange.types import NotYet

    with pytest.raises(NotYet, match="1.11"):
        fb_pack.pack().refresh(tmp_path / "x.xlsx", {})


def test_a_layout2_book_refreshes_and_takes_the_current_stamp(tmp_path):
    import shutil
    from pathlib import Path

    fixture = Path(H.__file__).parent / "fixtures" / "layout2-book.xlsx"
    path = tmp_path / "layout2.xlsx"
    shutil.copyfile(fixture, path)
    report = hb_pack.pack().refresh(path, _fresh({1: {"quantity": "32.000"}}))
    assert report.clean and report.baseline_replaced
    stamp = json.loads(H.open_book(path)["_wb"]["A1"].value)
    assert stamp["schema"] == 1 and stamp["extra"]["upgraded_from"] == 2
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 32
    assert _read(path).ops == []
