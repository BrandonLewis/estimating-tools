"""The Bid Form against BidSheet.ai's figures in the fixture, and its live
inputs (markup, scope, bid unit price override)."""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.tests._formula_eval import evaluate
from estimating_tools.heavycivil import layout, model, style
from estimating_tools.heavycivil.columns import BF


def _ctx(doc):
    wb = model.parse(doc)
    return wb, layout.plan(wb, style.load_style())


def _f(v):
    return 0.0 if v in (None, "") else float(v)


def _eval(book, tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    return evaluate(book, folder)


def test_estimate_figures_match_bidsheet(doc, evaluated):
    wb, plan = _ctx(doc)
    e, rows = wb.estimate, plan.bid_inputs
    assert _f(evaluated[f"Bid Form!C{rows['direct_cost']}"]) == pytest.approx(
        float(e.total_estimated_cost), abs=0.005)
    assert _f(evaluated[f"Bid Form!C{rows['markup_total']}"]) == pytest.approx(
        float(e.markup_total), abs=0.005)
    assert _f(evaluated[f"Bid Form!C{rows['bid_factor']}"]) == pytest.approx(
        float(e.live_bid_factor), abs=1e-9)
    assert _f(evaluated[f"Bid Form!C{rows['excluded_cost']}"]) == pytest.approx(
        float(e.excluded_cost), abs=0.005)


def test_item_bid_prices_and_totals_match(doc, evaluated):
    wb, plan = _ctx(doc)
    for item in wb.items:
        r = plan.bid_rows[item.id].row
        assert _f(evaluated[f"Bid Form!{BF.PRICE}{r}"]) == pytest.approx(
            float(item.bid_unit_price or 0), abs=0.005), item.item_number
        assert _f(evaluated[f"Bid Form!{BF.TOTAL}{r}"]) == pytest.approx(
            float(item.bid_total or 0), abs=0.005), item.item_number


def test_excluded_item_has_no_bid_price(doc, evaluated):
    wb, plan = _ctx(doc)
    x1 = next(i for i in wb.items if i.scope == "excluded")
    r = plan.bid_rows[x1.id].row
    assert evaluated[f"Bid Form!{BF.PRICE}{r}"] in (None, "")
    assert evaluated[f"Bid Form!{BF.TOTAL}{r}"] in (None, "")


def test_bid_total_definitions_match(doc, evaluated):
    wb, plan = _ctx(doc)
    assert plan.bid_total_rows
    for row in plan.bid_total_rows:
        assert _f(evaluated[f"Bid Form!{BF.TOTAL}{row.row}"]) == pytest.approx(
            float(row.obj.amount), abs=0.005), row.obj.name


def test_markup_edit_moves_factor_and_bid(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    before = _eval(book, tmp_path, "a")
    book["Bid Form"][f"C{plan.bid_inputs['markup_percentage']}"] = 20
    after = _eval(book, tmp_path, "b")
    f_row = plan.bid_inputs["bid_factor"]
    assert _f(after[f"Bid Form!C{f_row}"]) > _f(before[f"Bid Form!C{f_row}"])
    # 1 + (18095.00 x 20% + 250) / 18095.00
    assert _f(after[f"Bid Form!C{f_row}"]) == pytest.approx(1 + (3619.00 + 250) / 18095.00)
    primary = next(r for r in plan.bid_total_rows if r.obj.is_primary).row
    assert _f(after[f"Bid Form!{BF.TOTAL}{primary}"]) > _f(before[f"Bid Form!{BF.TOTAL}{primary}"])


def test_excluding_an_item_moves_it_to_excluded_cost(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    b3 = next(i for i in wb.items if i.item_number == "B3")
    r = plan.bid_rows[b3.id].row
    book["Bid Form"][f"{BF.SCOPE}{r}"] = "excluded"
    ev = evaluate(book, tmp_path)
    assert ev[f"Bid Form!{BF.PRICE}{r}"] in (None, "")
    excl = _f(ev[f"Bid Form!C{plan.bid_inputs['excluded_cost']}"])
    assert excl == pytest.approx(float(wb.estimate.excluded_cost)
                                 + _f(ev[f"Bid Form!{BF.COST}{r}"]), abs=0.01)
    # B3 leaves the factor base too: TEC drops by its calculate_total (20 x 166.88).
    tec = _f(ev[f"Bid Form!C{plan.bid_inputs['direct_cost']}"])
    assert tec == pytest.approx(18095.00 - 3337.60, abs=0.005)


def test_override_wins(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    item = next(i for i in wb.items if i.item_number == "12")
    r = plan.bid_rows[item.id].row
    book["Bid Form"][f"{BF.OVERRIDE}{r}"] = 99.99
    ev = evaluate(book, tmp_path)
    assert _f(ev[f"Bid Form!{BF.PRICE}{r}"]) == pytest.approx(99.99)
    assert _f(ev[f"Bid Form!{BF.TOTAL}{r}"]) == pytest.approx(999.90)


def test_bid_factor_shows_three_decimals(doc, book):
    _, plan = _ctx(doc)
    cell = book["Bid Form"][f"C{plan.bid_inputs['bid_factor']}"]
    assert cell.number_format == "0.000"
