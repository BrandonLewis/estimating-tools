"""The heavybook pack is a template pack (version 2): it builds every sheet
from template.xlsx, its book reads back clean, two builds are byte-identical,
and its declaration is the template's."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from openpyxl import load_workbook

from estimating_tools.estimate_spec import cli
from estimating_tools.exchange.facts import read_facts
from estimating_tools.exchange.types import BuildRefused
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.tests import _readback as H

AT = "2026-10-20T09:00:00Z"
TABS = ["Bid Form", "Recap", "Cost Report", "Crews", "Rates", "Schedule", "Checks", "Flat",
        "Allocation", "Bid Coverage", "_cal", "_wb", "_templates"]


def _build(tmp_path, name="book.xlsx", doc=None):
    out = tmp_path / name
    hb_pack.pack().build(doc or H.fixture_doc(), out, options={"exported_at": AT})
    return out


def test_it_is_a_template_pack_of_version_2():
    p = hb_pack.pack()
    assert (p.name, p.version) == ("heavybook", "2")
    assert p.declaration().kind == "template"


def test_the_book_has_every_sheet_and_only_machinery_hidden(tmp_path):
    wb = load_workbook(_build(tmp_path))
    assert wb.sheetnames == TABS
    assert [ws.title for ws in wb.worksheets if ws.sheet_state != "visible"] == [
        "_cal", "_wb", "_templates"]
    assert wb.custom_doc_props["estimate_format"].value == "heavybook 2"


def test_it_reads_back_clean_and_detects(tmp_path):
    book = _build(tmp_path)
    assert hb_pack.pack().read(book).change_set.ops == []
    assert hb_pack.pack().detect(read_facts(book)) == "ok"


def test_two_builds_write_the_same_bytes(tmp_path):
    assert _build(tmp_path, "a.xlsx").read_bytes() == _build(tmp_path, "b.xlsx").read_bytes()


def test_a_style_pack_is_ignored_with_a_warning(tmp_path, capsys):
    out = tmp_path / "s.xlsx"
    hb_pack.pack().build(H.fixture_doc(), out, options={"exported_at": AT, "style": "anything"})
    assert "the book's look is its template now" in capsys.readouterr().err
    assert out.exists()


def _copy_of_the_template(tmp_path, edit=None, pack=None):
    import estimating_tools.heavybook.template as shipped

    d = tmp_path / "our-template"
    shutil.copytree(Path(shipped.__file__).parent, d,
                    ignore=shutil.ignore_patterns("__init__.py", "__pycache__"))
    if edit is not None:
        wb = load_workbook(d / "template.xlsx")
        edit(wb)
        wb.save(d / "template.xlsx")
    if pack is not None:
        doc = yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8"))
        doc["pack"].update(pack)
        (d / "pack.yaml").write_bytes(yaml.safe_dump(doc, sort_keys=False).encode())
    return d


def test_a_copy_of_the_template_builds_and_reads_back(tmp_path):
    d = _copy_of_the_template(tmp_path, edit=lambda wb: wb["Recap"].__setitem__(
        "A1", "Recap -- our layout"))
    out = tmp_path / "ours.xlsx"
    hb_pack.pack().build(H.fixture_doc(), out, options={"exported_at": AT, "template": str(d)})
    assert load_workbook(out)["Recap"]["A1"].value == "Recap -- our layout"
    assert hb_pack.pack().read(out).change_set.ops == []
    assert hb_pack.pack().detect(read_facts(out)) == "ok"


def test_a_template_of_another_pack_is_refused(tmp_path):
    d = _copy_of_the_template(tmp_path, pack={"name": "other-book"})
    with pytest.raises(BuildRefused, match="declares pack 'other-book'"):
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "x.xlsx",
                             options={"template": str(d)})
    assert not (tmp_path / "x.xlsx").exists()


def test_a_template_the_lint_refuses_writes_nothing(tmp_path):
    d = _copy_of_the_template(tmp_path, edit=lambda wb: wb["Cost Report"].__setitem__(
        "B5", "leftover"))
    with pytest.raises(BuildRefused, match="Cost Report!B5"):
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "x.xlsx",
                             options={"template": str(d)})
    assert not (tmp_path / "x.xlsx").exists()


@pytest.mark.parametrize("argv", [["build", "--pack", "heavybook"], ["heavybook", "build"]])
def test_the_cli_takes_template(tmp_path, argv):
    d = _copy_of_the_template(tmp_path)
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()), encoding="utf-8")
    out = tmp_path / "e1.xlsx"
    assert cli.main(argv + [str(src), "-o", str(out), "--template", str(d),
                            "--recalc", "off"]) == 0
    assert out.exists()


def test_heavybook_build_takes_allow_dropped(tmp_path, capsys):
    from openpyxl.comments import Comment

    d = _copy_of_the_template(tmp_path, edit=lambda wb: setattr(
        wb["_templates"]["B8"], "comment", Comment("a hint", "author")))
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()), encoding="utf-8")
    out = tmp_path / "e1.xlsx"
    argv = ["heavybook", "build", str(src), "-o", str(out), "--template", str(d),
            "--recalc", "off"]
    assert cli.main(argv) == 1
    assert "pass --allow-dropped" in capsys.readouterr().err and not out.exists()
    assert cli.main(argv + ["--allow-dropped"]) == 0
    assert "_templates!B8: a note on a prototype row" in capsys.readouterr().out
    assert out.exists()


def test_a_template_copy_is_never_its_own_output(tmp_path):
    d = _copy_of_the_template(tmp_path)
    before = (d / "template.xlsx").read_bytes()
    with pytest.raises(BuildRefused, match="is the template itself"):
        hb_pack.pack().build(H.fixture_doc(), d / "template.xlsx",
                             options={"template": str(d)})
    assert (d / "template.xlsx").read_bytes() == before


def test_a_template_of_a_newer_pack_version_is_refused(tmp_path):
    """This plugin reads heavybook books of versions 1 and 2: a copy that
    bumps its version builds books the plugin would refuse to read."""
    d = _copy_of_the_template(tmp_path, pack={"version": "3"})
    with pytest.raises(BuildRefused, match="version '3'.*update the plugin"):
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "x.xlsx",
                             options={"template": str(d)})
    assert not (tmp_path / "x.xlsx").exists()


def test_a_template_of_the_code_built_version_is_refused(tmp_path):
    """Version 1 books still read, but they were the code writers': a
    template builds version 2 only."""
    d = _copy_of_the_template(tmp_path, pack={"version": "1"})
    with pytest.raises(BuildRefused, match="version '1'.*keep the copy's version"):
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "x.xlsx",
                             options={"template": str(d)})
    assert not (tmp_path / "x.xlsx").exists()


def test_a_directory_without_a_template_pack_is_refused(tmp_path):
    (tmp_path / "pack.yaml").write_bytes(b"pack: {name: heavybook}\n")
    with pytest.raises(BuildRefused, match="template.xlsx missing"):
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "x.xlsx",
                             options={"template": str(tmp_path)})


@pytest.mark.parametrize("text", [b"pack: [unclosed\n", b"- a list\n", b"pack: heavybook\n",
                                  b"pack: [heavybook, 2]\n"])
def test_a_pack_yaml_that_does_not_load_is_refused(tmp_path, text):
    d = _copy_of_the_template(tmp_path)
    (d / "pack.yaml").write_bytes(text)
    with pytest.raises(BuildRefused, match="our-template"):
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "x.xlsx",
                             options={"template": str(d)})


def test_a_refresh_that_moves_dates_rewrites_the_calendar_and_the_schedule(tmp_path):
    from datetime import date

    from estimating_tools.exchange import display, model
    from estimating_tools.xlcalc import cache_values

    book = _build(tmp_path)
    fresh = H.fixture_doc()
    act = next(a for a in fresh["activities"] if a["id"] == 1)
    act.update(start_date="2026-11-09", finish_date="2026-11-11", v="9" * 16)
    other = next(a for a in fresh["activities"] if a["id"] == 6)
    other.update(start_date="2026-11-09", finish_date="2026-11-10", v="8" * 16)
    report = hb_pack.pack().refresh(book, fresh)
    assert report.clean and report.structural == []
    days = [d.day for d in display.working_days(model.parse(fresh))]
    ws = load_workbook(book)["_cal"]
    have = [ws[f"A{r}"].value for r in range(1, ws.max_row + 1)
            if ws[f"A{r}"].value is not None]
    assert [d.date() for d in have] == days[:len(have)]
    assert len(have) == ws.max_row                       # no gap in the calendar
    assert have[0].date() == date(2026, 11, 2)           # a week before the first start
    cache_values(book)
    sc = load_workbook(book, data_only=True)["Schedule"]
    row = next(r for r in range(5, sc.max_row + 1) if sc[f"H{r}"].value == 1)
    assert sc[f"D{row}"].value.date() == date(2026, 11, 9)
    assert sc[f"F{row}"].value.date() == date(2026, 11, 11)
    assert hb_pack.pack().read(book).change_set.ops == []


def _names(path):
    wb = load_workbook(path)
    return {n: wb.defined_names[n].attr_text for n in wb.defined_names
            if n.startswith("hc.") and not n.startswith("hc.tpl.") and n != "hc.layout"}


def test_the_sheet_names_cover_the_placed_rows_as_the_code_build_did(tmp_path):
    """The template's names over a fill region end at its sentinel row so a
    fill's inserts grow them; after the fill they cover exactly the rows the
    code build's names covered (heading row included where it was, the
    sentinel never): ``hc.bid_totals`` the total rows, ``hc.checks`` the
    header and the check rows."""
    got = _names(_build(tmp_path))
    assert got == _names(Path(H.__file__).parent / "fixtures" / "v1-book.xlsx")
    assert got["hc.bid_totals"] == "'Bid Form'!$A$22:$I$23"
    implicit = _names(_build(tmp_path, "implicit.xlsx", H.implicit_doc()))
    assert implicit["hc.bid_totals"] == "'Bid Form'!$A$22:$I$22"
