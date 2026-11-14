"""Checks sets the book's figures beside BidSheet.ai's (rules 11 and 12): a
read-model build only; a spec book has none."""
from __future__ import annotations

import copy

from openpyxl import load_workbook

from estimating_tools import xlcalc
from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import from_model
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.estimate_spec.tests._fieldbook import EXAMPLE, fieldbook_pack


def _checks(path):
    xlcalc.cache_or_warn(path)
    ws = load_workbook(path, data_only=True)["Checks"]
    return ws, [[c.value for c in row[:6]] for row in ws.iter_rows(min_row=1)]


def _rule(rows, n):
    return [r for r in rows if r[0] == n]


def test_the_server_figures_are_summed_per_item():
    cfg = from_model.from_model(X.payload())
    assert [i["server_cost"] for i in cfg["items"]] == [1520, 52158.4]
    server = cfg["_server"]
    assert "items" not in server
    assert server["bid"] == 20163
    assert server["markup_amount"] == 0


def test_each_items_direct_cost_matches_bidsheets(tmp_path):
    _ws, rows = _checks(X.book(tmp_path))
    r11 = _rule(rows, 11)
    assert [str(r[2]) for r in r11] == ["1", "2"]
    assert [r[5] for r in r11] == ["✓", "✓"]
    assert [round(r[4], 2) for r in r11] == [1520, 52158.4]
    assert [round(r[3], 2) for r in r11] == [1520, 52158.4]


def test_a_server_cost_that_differs_fails_its_row(tmp_path):
    doc = X.payload()
    for act in doc["activities"]:
        if act["id"] == 23:
            act["cost"] = "13000.00"
    cfg = from_model.from_model(doc)
    wb = B.generate(cfg, fieldbook_pack(),
                    exchange=X.identity.Baseline(payload=doc, host=X.HOST,
                                                 exported_at=X.EXPORTED_AT))
    path = tmp_path / "off.xlsx"
    wb.save(path)
    _ws, rows = _checks(path)
    assert [r[5] for r in _rule(rows, 11)] == ["✓", "✗"]


def test_the_bid_row_shows_both_bids_and_does_not_count(tmp_path):
    ws, rows = _checks(X.book(tmp_path))
    (r12,) = _rule(rows, 12)
    assert r12[4] == 20163 and r12[5] == "—"
    assert "markup $" in r12[2]
    assert isinstance(r12[3], (int, float))
    passing = ws["B2"].value
    counted = ws["D2"].value
    marks = [r[5] for r in rows if r[0] != "#"]
    assert counted == marks.count("✓") + marks.count("✗")
    assert passing == marks.count("✓")


def test_a_spec_book_has_no_server_rows(tmp_path):
    import yaml
    cfg = yaml.safe_load(EXAMPLE.read_text())
    assert "_server" not in cfg
    path = tmp_path / "spec.xlsx"
    B.generate(cfg, fieldbook_pack()).save(path)
    _ws, rows = _checks(path)
    assert not [r for r in rows if r[0] in (11, 12)]


def test_dotted_item_numbers_build_and_each_row_shows_its_own_cost(tmp_path):
    doc = X.payload()
    doc["items"][0]["item_number"] = "2.1"
    doc["items"][1]["item_number"] = "203.05"
    cfg = from_model.from_model(doc)
    wb = B.generate(cfg, fieldbook_pack(),
                    exchange=X.identity.Baseline(payload=doc, host=X.HOST,
                                                 exported_at=X.EXPORTED_AT))
    path = tmp_path / "dotted.xlsx"
    wb.save(path)
    _ws, rows = _checks(path)
    r11 = _rule(rows, 11)
    assert [str(r[2]) for r in r11] == ["2.1", "203.05"]
    assert [round(r[4], 2) for r in r11] == [1520, 52158.4]
    assert [r[5] for r in r11] == ["✓", "✓"]
