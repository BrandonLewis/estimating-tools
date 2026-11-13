"""A template pack behind the ``Pack`` protocol (``exchange.template``):
detection from the stamp, the insert templates, patch and refresh through
the engine, what it shows as of export, and the CLI's ``build --pack``."""
from __future__ import annotations

import copy
import json

import pytest
from openpyxl import load_workbook
from openpyxl.comments import Comment

from estimating_tools.estimate_spec import cli
from estimating_tools.exchange import registry
from estimating_tools.exchange.declaration import DeclarationError
from estimating_tools.exchange.facts import read_facts
from estimating_tools.exchange.template import TemplatePack, as_of_export
from estimating_tools.exchange.tests import _template as T
from estimating_tools.exchange.types import BuildRefused
from estimating_tools.heavybook.tests import _readback as H
from estimating_tools.heavybook.tests.test_patch import _server
from estimating_tools.xlcalc import cache_values

AT = "2026-11-06T09:00:00Z"
SHARES_ADDED = ("BidSheet.ai added or removed share rows, which the Shares sheet lays out and "
                "the book prices from -- apply this book's edits, then rebuild it from "
                "BidSheet.ai")
SHARES_CARRIED = ("Shares: the share rows were found changed in BidSheet.ai earlier (a patch "
                  "took its new baseline); the sheet shows them as of the last build -- apply "
                  "this book's edits, then rebuild it from BidSheet.ai to show them")


@pytest.fixture
def pack(tmp_path):
    return TemplatePack(T.make(tmp_path / "pack"))


def _built(pack, tmp_path, name="book.xlsx"):
    pack.build(H.fixture_doc(), tmp_path / name, options={"exported_at": AT})
    return tmp_path / name


def _priced(book, row):
    """Row ``row``'s total on the blocks sheet, as xlcalc computes it."""
    cache_values(book)
    return load_workbook(book, data_only=True)[T.TAB][f"F{row}"].value


def test_it_names_itself_from_its_declaration(pack):
    assert (pack.name, pack.version, pack.contract) == ("mini-book", "1", "1")
    assert pack.declaration().kind == "template"
    assert [(k.kind, k.name) for k in pack.templates()] == [
        ("activity", "mb.tpl.activity"), ("stepped", "mb.tpl.stepped"),
        ("step", "mb.tpl.step"), ("resource", "mb.tpl.resource"), ("member", "mb.tpl.member")]


def test_a_declaration_of_another_kind_is_refused(tmp_path):
    doc = copy.deepcopy(T.DECLARATION)
    doc["kind"] = "code"
    pack = TemplatePack(T.make(tmp_path / "pack", declaration=doc))
    with pytest.raises(DeclarationError, match="a template pack's is 'template'"):
        pack.declaration()
    with pytest.raises(BuildRefused, match="mini-book"):
        pack.build(H.fixture_doc(), tmp_path / "book.xlsx", options={})


def test_it_detects_its_own_books_only(pack, tmp_path):
    book = _built(pack, tmp_path)
    assert pack.detect(read_facts(book)) == "ok"
    heavybook = H.build_book(H.fixture_doc(), tmp_path / "hb.xlsx")
    assert pack.detect(read_facts(heavybook)) == "none"
    facts = read_facts(book)
    raw = json.loads(facts.names["exchange.stamp"])
    newer = dict(raw, schema=raw["schema"] + 1)
    assert pack.detect(type(facts)(path="x", properties=facts.properties,
                                   names={"exchange.stamp": json.dumps(newer)})) == "newer"
    assert pack.detect(type(facts)(path="x", properties=facts.properties,
                                   names={"exchange.stamp": "{"})) == "bad"


def test_a_typed_resource_is_patched_from_its_prototype(pack, tmp_path):
    book = _built(pack, tmp_path)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    end = next(r for r in range(T.FIRST, ws.max_row + 1)
               if ws[f"{T.KIND}{r}"].value == "END" and ws[f"{T.KIND}{r - 1}"].value
               == "RESOURCE" and ws[f"{T.ID}{r - 1}"].value == 3)
    ws.insert_rows(end)
    ws[f"B{end}"], ws[f"C{end}"], ws[f"D{end}"], ws[f"E{end}"] = "Pump", 1, "equipment", 250
    H.save_book(wb, book)
    first = pack.read(book)
    assert first.problems == [] and [op["op"] for op in first.change_set.ops] == [
        "resource.create"]
    fresh, plan = _server(H.fixture_doc(), first.change_set)
    report = pack.patch(book, first.change_set, plan, fresh)
    assert report.baseline_replaced and report.problems == []
    ws = H.open_book(book)[T.TAB]
    assert (ws[f"{T.KIND}{end}"].value, ws[f"{T.ID}{end}"].value, ws[f"F{end}"].value,
            ws[f"{T.OWNER}{end}"].value) == (
        "RESOURCE", 50, T._resource_total(end), T._owner_row(end))
    assert pack.read(book).change_set.ops == []
    # It prices through its activity's multiplier (Walls, count 2): the
    # helper came from the filled book's prototype.
    assert _priced(book, end) == pytest.approx(1 * 250 * 2)


def test_a_server_added_resource_is_inserted_and_priced_through_the_helper(pack, tmp_path):
    book = _built(pack, tmp_path)
    fresh = H.fixture_doc()
    res = next(r for r in fresh["resources"] if r["id"] == 4)          # Ties: 3 x 2 counts
    fresh["resources"].append(dict(res, id=50, name="Server tie wire", quantity="2.000",
                                   unit_cost="5.00", sort_order=9, v="5" * 16))
    report = pack.refresh(book, fresh)
    assert report.clean and report.rows_added == 1
    ws = H.open_book(book)[T.TAB]
    row = next(r for r in range(T.FIRST, ws.max_row + 1)
               if ws[f"{T.KIND}{r}"].value == "RESOURCE" and ws[f"{T.ID}{r}"].value == 50)
    assert ws[f"{T.OWNER}{row}"].value == T._owner_row(row)
    assert _priced(book, row) == pytest.approx(2 * 5 * 6)
    assert pack.read(book).change_set.ops == []


def test_a_server_only_change_is_refreshed(pack, tmp_path):
    book = _built(pack, tmp_path)
    fresh = H.fixture_doc()
    for res in fresh["resources"]:
        if res["id"] == 2:
            res.update(quantity="3.000", v="aaaaaaaaaaaaaaaa")
    report = pack.refresh(book, fresh)
    assert report.clean and report.baseline_replaced
    assert pack.read(book).change_set.ops == []


def test_a_changed_share_fraction_is_rewritten_in_place(pack, tmp_path):
    book = _built(pack, tmp_path)
    fresh = H.fixture_doc()
    fresh["shares"][4]["fraction"] = "0.6"
    report = pack.refresh(book, fresh)
    assert report.clean and report.baseline_replaced
    ws = load_workbook(book)[T.SHARES]
    row = next(r for r in range(2, ws.max_row + 1) if ws[f"G{r}"].value == "5:1:1")
    assert ws[f"C{row}"].value == 0.6


def test_a_share_added_in_bidsheet_needs_a_rebuild(pack, tmp_path):
    book = _built(pack, tmp_path)
    before = book.read_bytes()
    fresh = H.fixture_doc()
    fresh["shares"].append(dict(fresh["shares"][0], activity_id=2, item_id=2, fraction="0.1"))
    report = pack.refresh(book, fresh)
    assert not report.clean and report.structural == [SHARES_ADDED]
    assert book.read_bytes() == before


def test_a_new_warning_is_a_note_and_the_export_time_is_rewritten(pack, tmp_path):
    book = _built(pack, tmp_path)
    fresh = H.fixture_doc()
    fresh["activities"][0]["warnings"] = ["Check the crew"]
    report = pack.refresh(book, fresh)
    assert report.clean
    assert any("1 warning row(s) BidSheet.ai has now" in n for n in report.notes)
    assert load_workbook(book)[T.TAB]["A2"].value != AT           # the new export time


def test_what_the_test_pack_shows_as_of_export_is_laid_out(pack):
    assert as_of_export(pack.declaration()) == ()     # Crews and Rates lay them out


@pytest.fixture
def installed(monkeypatch, pack, tmp_path):
    monkeypatch.setattr(registry, "discover", lambda: registry.Discovery([pack], []))
    monkeypatch.setenv("ESTIMATING_HOME", str(tmp_path / "home"))
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()), encoding="utf-8")
    return src


def test_the_cli_builds_and_reads_a_template_book(installed, tmp_path, capsys):
    out = tmp_path / "e1.xlsx"
    assert cli.main(["build", "--pack", "mini-book", str(installed), "-o", str(out),
                     "--exported-at", AT, "--recalc", "off"]) == 0
    assert cli.main(["read", str(out)]) == 0
    text = capsys.readouterr().out
    assert "pack: mini-book 1" in text and "no changes" in text


def test_the_cli_refuses_a_dropped_prototype_feature_unless_allowed(monkeypatch, tmp_path,
                                                                     capsys):
    pack = TemplatePack(T.make(tmp_path / "noted", edit=lambda wb: setattr(
        wb[T.PROTO]["B17"], "comment", Comment("a hint", "author"))))
    monkeypatch.setattr(registry, "discover", lambda: registry.Discovery([pack], []))
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()), encoding="utf-8")
    out = tmp_path / "e1.xlsx"
    argv = ["build", "--pack", "mini-book", str(src), "-o", str(out), "--recalc", "off"]
    assert cli.main(argv) == 1
    assert "pass --allow-dropped" in capsys.readouterr().err and not out.exists()
    assert cli.main(argv + ["--allow-dropped"]) == 0
    assert f"not copied onto the filled rows: {T.PROTO}!B17: a note on a prototype row" in \
        capsys.readouterr().out


def test_a_share_added_while_a_patch_took_the_baseline_stays_stale(pack, tmp_path):
    from estimating_tools.exchange import stamp as exchange_stamp

    book = _built(pack, tmp_path)
    assert "stale" not in exchange_stamp.read(book).raw          # a fresh build
    wb = H.open_book(book)
    ws = wb[T.TAB]
    row = next(r for r in range(T.FIRST, ws.max_row + 1)
               if ws[f"{T.KIND}{r}"].value == "RESOURCE" and ws[f"{T.ID}{r}"].value == 2)
    ws[f"C{row}"] = 7
    H.save_book(wb, book)
    first = pack.read(book)
    fresh, plan = _server(H.fixture_doc(), first.change_set)
    fresh["shares"].append(dict(fresh["shares"][0], activity_id=2, item_id=2, fraction="0.1"))
    report = pack.patch(book, first.change_set, plan, fresh)
    assert report.baseline_replaced and SHARES_ADDED in report.notes
    assert exchange_stamp.read(book).raw["stale"] == ["shares.SHARE"]
    # Nothing new in BidSheet.ai: current, and the earlier finding is a note.
    again = pack.refresh(book, fresh)
    assert again.current and again.notes == [SHARES_CARRIED]
    # Another user's change since: taken -- the baseline already matches
    # BidSheet.ai's shares, so the carried name does not block it.
    other = copy.deepcopy(fresh)
    next(r for r in other["resources"] if r["id"] == 4).update(quantity="5.000", v="6" * 16)
    later = pack.refresh(book, other)
    assert later.clean and later.baseline_replaced and SHARES_CARRIED in later.notes
    assert later.structural == []
    assert exchange_stamp.read(book).raw["stale"] == ["shares.SHARE"]
    assert pack.read(book).change_set.ops == []
    # A share change found now is new: refused, the book untouched.
    newer = copy.deepcopy(other)
    newer["shares"].append(dict(newer["shares"][0], activity_id=3, item_id=2, fraction="0.2"))
    before = book.read_bytes()
    refused = pack.refresh(book, newer)
    assert not refused.clean and refused.structural == [SHARES_ADDED]
    assert book.read_bytes() == before


def _warning_rows(book):
    ws = load_workbook(book)[T.LINES]
    return [(ws[f"G{r}"].value, ws[f"A{r}"].value, ws[f"B{r}"].value)
            for r in range(1, ws.max_row + 1) if ws[f"F{r}"].value == "WARNING"]


def _with_warnings(pack, tmp_path, *texts):
    doc = H.fixture_doc()
    doc["activities"][0]["warnings"] = list(texts)
    tmp_path.mkdir(parents=True, exist_ok=True)
    book = tmp_path / "book.xlsx"
    pack.build(doc, book, options={"exported_at": AT})
    return book


def test_a_warning_is_identified_by_its_activity_and_text(pack, tmp_path):
    book = _with_warnings(pack, tmp_path, "One", "Two", "Three")
    ids = [i for i, _a, _t in _warning_rows(book)]
    assert len(set(ids)) == 3 and all(i.startswith("1:") for i in ids)
    again = _with_warnings(pack, tmp_path / "x", "Three", "One")
    assert [i for i, _a, _t in _warning_rows(again)] == [ids[2], ids[0]]


def test_a_warning_removed_in_bidsheet_is_blanked_with_a_note(pack, tmp_path):
    book = _with_warnings(pack, tmp_path, "One", "Two", "Three")
    fresh = H.fixture_doc()
    fresh["activities"][0]["warnings"] = ["One", "Three"]
    report = pack.refresh(book, fresh)
    assert report.clean
    assert [t for _i, _a, t in _warning_rows(book)] == ["One", None, "Three"]
    assert [a for _i, a, _t in _warning_rows(book)][1] is None
    assert ("Lines: 1 warning row(s) BidSheet.ai no longer has are blanked; a rebuild "
            "removes them") in report.notes
    assert pack.refresh(book, fresh).current                 # nothing left to do


def test_a_changed_warning_is_a_removed_row_and_a_new_one(pack, tmp_path):
    book = _with_warnings(pack, tmp_path, "One", "Two")
    fresh = H.fixture_doc()
    fresh["activities"][0]["warnings"] = ["One", "Two changed"]
    report = pack.refresh(book, fresh)
    assert report.clean
    assert [t for _i, _a, t in _warning_rows(book)] == ["One", None]
    assert any("1 warning row(s) BidSheet.ai has now" in n for n in report.notes)
    assert any("1 warning row(s) BidSheet.ai no longer has" in n for n in report.notes)


def test_two_alike_warnings_on_one_activity_keep_their_own_rows(pack, tmp_path):
    book = _with_warnings(pack, tmp_path, "Same", "Same")
    fresh = H.fixture_doc()
    fresh["activities"][0]["warnings"] = ["Same", "Same"]
    fresh["activities"][0]["name"] = "Renamed"
    assert pack.refresh(book, fresh).clean
    assert [t for _i, _a, t in _warning_rows(book)] == ["Same", "Same"]


def _lines_resources(book):
    ws = load_workbook(book)[T.LINES]
    return {ws[f"G{r}"].value: ws[f"B{r}"].value for r in range(1, ws.max_row + 1)
            if ws[f"F{r}"].value == "RESOURCE"}


def test_a_resource_added_in_bidsheet_is_noted_where_a_display_sheet_lists_it(pack, tmp_path):
    book = _built(pack, tmp_path)
    fresh = H.fixture_doc()
    res = next(r for r in fresh["resources"] if r["id"] == 4)
    fresh["resources"].append(dict(res, id=50, name="Server tie wire", v="5" * 16))
    report = pack.refresh(book, fresh)
    assert report.clean and report.rows_added == 1
    assert 50 not in _lines_resources(book)
    assert ("Lines: 1 resource row(s) BidSheet.ai has now are not listed under their "
            "activity -- rebuild to list them") in report.notes


def test_a_resource_deleted_in_bidsheet_is_blanked_where_a_display_sheet_lists_it(pack,
                                                                                  tmp_path):
    book = _built(pack, tmp_path)
    fresh = H.fixture_doc()
    fresh["resources"] = [r for r in fresh["resources"] if r["id"] != 4]
    report = pack.refresh(book, fresh)
    assert report.clean and report.rows_removed == 1
    assert _lines_resources(book)[4] is None
    assert ("Lines: 1 resource row(s) BidSheet.ai no longer has are blanked; a rebuild "
            "removes them") in report.notes


def test_a_refresh_with_only_a_new_export_time_asks_for_no_recalculation(pack, tmp_path):
    from estimating_tools.exchange import model
    from estimating_tools.exchange.reader import run

    book = _built(pack, tmp_path)
    opened = run(book, pack=pack)[0]
    try:
        same = pack.refresh_extras(opened, H.fixture_doc(), model.parse(H.fixture_doc()),
                                   exported_at="2026-11-07T10:00:00Z")
        renamed = H.fixture_doc()
        renamed["estimate"]["name"] = "Renamed estimate"
        other = pack.refresh_extras(opened, renamed, model.parse(renamed),
                                    exported_at="2026-11-07T10:00:00Z")
    finally:
        opened.wb.close()
    assert same.cells == {T.TAB: {"A2": "2026-11-07T10:00:00Z"}} and not same.recalc
    assert other.cells[T.TAB]["A1"] == "Renamed estimate" and other.recalc
