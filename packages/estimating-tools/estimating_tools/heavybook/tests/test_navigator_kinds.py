"""Estimate Navigator's HeavyBook test fixture, written from the golden book
and checked for drift: ``excel-addin/tests/fixtures/heavycivil-kinds.json``.

The add-in's ``node --test`` suites run against the Cost Report's and Crews'
kind, id and parent columns of the fixture book, spelled as Office.js hands
them back (a blank cell is ""; a number is a number; a formula cell -- a
block row's owner tag -- its computed value, here pycel's), plus the book's
layout JSON (``_wb!A1``) without its baseline. Regenerate with
UPDATE_GOLDEN=1 after a reviewed change to the build.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from estimating_tools.heavybook.columns import CR, CW
from estimating_tools.heavybook.layout import FIRST_ROW

#: The repo root: tests/ -> heavycivil -> estimating_tools -> estimating-tools -> packages.
ROOT = Path(__file__).resolve().parents[5]
KINDS = ROOT / "excel-addin" / "tests" / "fixtures" / "heavycivil-kinds.json"
#: Per sheet key: (field, column letter), in the order the JSON lists them.
COLUMNS = {"cost_report": (("kind", CR.KIND), ("id", CR.ID), ("parent", CR.PARENT)),
           "crews": (("kind", CW.KIND), ("id", CW.ID), ("parent", CW.CREW))}


def _office(value):
    """A cell value as Office.js ``Range.values`` returns it."""
    return "" if value is None else value


def _value(ws, evaluated, tab, letter, r):
    """A cell as Office.js reads it: a formula cell (a block row's owner
    tag) by its computed value."""
    cell = ws[f"{letter}{r}"]
    if cell.data_type == "f":
        return evaluated[f"{tab}!{letter}{r}"]
    return cell.value


def kinds_fixture(book, evaluated) -> dict:
    from estimating_tools.exchange import stamp as exchange_stamp
    st = exchange_stamp.parse(json.loads(book["_wb"]["A1"].value))
    layout = dict(st.extra["layout"])
    out = {"source": "heavycivil/tests/fixtures/workbook.json, built by "
                     "heavycivil/tests/test_navigator_kinds.py",
           "first_row": FIRST_ROW, "layout": layout}
    for key, columns in COLUMNS.items():
        tab = layout["tabs"][key]
        ws = book[tab]
        rows = range(FIRST_ROW, ws.max_row + 1)
        out[key] = {field: [_office(_value(ws, evaluated, tab, letter, r)) for r in rows]
                    for field, letter in columns}
    return out


@pytest.mark.skipif(not KINDS.parent.is_dir(), reason="not run from a repo checkout")
def test_heavycivil_kinds_fixture_has_not_drifted(book, evaluated):
    got = json.loads(json.dumps(kinds_fixture(book, evaluated), sort_keys=True))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        KINDS.write_bytes((json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False)
                           + "\n").encode("utf-8"))
    assert got == json.loads(KINDS.read_text(encoding="utf-8")), (
        "excel-addin/tests/fixtures/heavycivil-kinds.json is stale: regenerate it with "
        "UPDATE_GOLDEN=1 pytest .../heavycivil/tests/test_navigator_kinds.py")


def test_the_fixture_columns_line_up(book, evaluated):
    data = kinds_fixture(book, evaluated)
    for key in COLUMNS:
        lengths = {len(v) for v in data[key].values()}
        assert len(lengths) == 1, key
    assert data["cost_report"]["kind"][0] == "ITEM"
    assert data["crews"]["kind"][0] == "CREW"
    assert data["layout"]["navigator"]["templates"]["stepped"] == "hc.tpl.stepped"
