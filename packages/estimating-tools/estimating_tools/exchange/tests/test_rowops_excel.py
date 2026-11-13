"""The writer's row ops on a real HeavyBook book, against the Excel simulator
the read-back suite trusts (``_fieldbook.paste_template_rows``,
``simulate_delete_row``): the same cells and formulas on every sheet, and
xlcalc prices both books the same."""
from __future__ import annotations

import re

import pytest
from openpyxl import load_workbook

from estimating_tools.estimate_spec.tests._fieldbook import (paste_template_rows,
                                                             simulate_delete_row)
from estimating_tools.exchange import rowops, writer
from estimating_tools.heavybook.tests import _readback as H
from estimating_tools.heavybook.tests._readback import evaluate

#: The sheets HeavyBook's declaration binds, and the stamp's: no #REF! there.
BOUND = {H.CR_TAB, H.CW_TAB, H.BF_TAB, H.RT_TAB, "_wb"}
#: Excel keeps a qualified #REF!'s sheet; the simulator drops it.
_QUALIFIED_REF = re.compile(r"(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!#REF!")


def _positions(path):
    wb = H.open_book(path)
    cr, cw = wb[H.CR_TAB], wb[H.CW_TAB]
    return {"end": H.cr_row(cr, "END", parent=2), "foreman": H.cr_row(cr, "RESOURCE", 3),
            "crew_end": H.cw_row(cw, "CREW_END", parent=1),
            "res": H.template_rows(wb, "hc.tpl.resource"),
            "mem": H.template_rows(wb, "hc.tpl.member"), "sheets": list(wb.sheetnames)}


def _ops(p):
    """Bottom-up on each sheet: the insert at activity 2's END first, then
    the Foreman row above it, so every op names the book's original rows."""
    return [rowops.InsertRows(H.CR_TAB, p["end"], "_templates", *p["res"]),
            rowops.DeleteRows(H.CR_TAB, p["foreman"]),
            rowops.InsertRows(H.CW_TAB, p["crew_end"], "_templates", *p["mem"])]


def _simulated(path, p):
    wb = H.open_book(path)
    paste_template_rows(wb, *p["res"], H.CR_TAB, p["end"])
    simulate_delete_row(wb[H.CR_TAB], p["foreman"])
    paste_template_rows(wb, *p["mem"], H.CW_TAB, p["crew_end"])
    return wb


def _cells(ws) -> dict:
    out = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is None:
                continue
            v = c.value
            if isinstance(v, str) and v.startswith("="):
                v = _QUALIFIED_REF.sub("#REF!", v)
            out[c.coordinate] = v
    return out


def _edited(tmp_path, cells=None):
    built = H.build_book(H.fixture_doc(), tmp_path / "b.xlsx")
    p = _positions(built)
    ours = tmp_path / "w.xlsx"
    ours.write_bytes(built.read_bytes())
    done = writer.edit(ours, rows=_ops(p), cells=cells and cells(p),
                       lost_ok=set(p["sheets"]) - BOUND)
    return built, p, ours, done


def test_the_writer_edits_a_heavybook_book_as_excel_does(tmp_path):
    built, p, ours, done = _edited(tmp_path)
    # The template's formulas find the Foreman's row by key, never by
    # address: deleting it leaves no #REF! anywhere (the code build's Checks
    # and Flat rows read it by address, and read #REF! as after Excel's own
    # delete).
    assert done.lost == []
    mine, excel = load_workbook(ours), _simulated(built, p)
    for title in p["sheets"]:
        assert _cells(mine[title]) == _cells(excel[title]), title
    first, last = p["res"]
    assert mine.defined_names["hc.tpl.resource"].attr_text == f"'_templates'!${first}:${last}"


LINE = {"B": "Gravel", "C": 2, "E": 10, "S": "material", "T": "production", "V": "N"}
MEMBER = {"A": "Laborer", "C": 1}


def _new_rows(p):
    m = rowops.RowMap(_ops(p))
    return m.inserted(0)[0], m.inserted(2)[0]


def _typed(p):
    res, mem = _new_rows(p)
    return {H.CR_TAB: {f"{k}{res}": v for k, v in LINE.items()},
            H.CW_TAB: {f"{k}{mem}": v for k, v in MEMBER.items()}}


def test_both_books_price_the_same(tmp_path):
    built, p, ours, _done = _edited(tmp_path, cells=_typed)
    res, mem = _new_rows(p)
    excel = _simulated(built, p)
    for k, v in LINE.items():
        excel[H.CR_TAB][f"{k}{res}"] = v
    for k, v in MEMBER.items():
        excel[H.CW_TAB][f"{k}{mem}"] = v
    mine = load_workbook(ours)
    act = H.cr_row(mine[H.CR_TAB], "ACTIVITY", 2)
    crew = H.cw_row(mine[H.CW_TAB], "CREW", 1)
    addresses = ([f"{H.CR_TAB}!{c}{r}" for r in (act, res) for c in "LMNOPQR"]
                 + [f"{H.CW_TAB}!{c}{crew}" for c in "IJ"])
    (tmp_path / "ours").mkdir()
    (tmp_path / "excel").mkdir()
    ev_mine, ev_excel = evaluate(mine, tmp_path / "ours"), evaluate(excel, tmp_path / "excel")
    for a in addresses:
        assert ev_mine[a] == pytest.approx(ev_excel[a]), a
    assert ev_mine[f"{H.CR_TAB}!O{act}"] == pytest.approx(40)     # 2 x 10 material, count 2
    assert ev_mine[f"{H.CW_TAB}!I{crew}"] == pytest.approx(4)     # 2 + 1 + the new 1
