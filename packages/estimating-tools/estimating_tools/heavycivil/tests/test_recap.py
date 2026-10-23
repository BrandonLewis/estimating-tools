"""The Recap reads the Cost Report and the Bid Form; its totals sum it."""
from __future__ import annotations

import pytest

from estimating_tools.heavycivil import layout, model, style
from estimating_tools.heavycivil.columns import BF, CR, RC


def _f(v):
    return 0.0 if v in (None, "") else float(v)


def test_recap_matches_cost_report_and_bid_form(doc, evaluated):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    total_direct = total_bid = 0.0
    for item in wb.items:
        r, cr = plan.recap_rows[item.id], plan.item_rows[item.id].row
        bf = plan.bid_rows[item.id].row
        assert _f(evaluated[f"Recap!{RC.DIRECT}{r}"]) == pytest.approx(
            _f(evaluated[f"Cost Report!{CR.TOTAL}{cr}"])), item.item_number
        assert _f(evaluated[f"Recap!{RC.TOTAL}{r}"]) == pytest.approx(
            _f(evaluated[f"Bid Form!{BF.TOTAL}{bf}"])), item.item_number
        total_direct += _f(evaluated[f"Recap!{RC.DIRECT}{r}"])
        total_bid += _f(evaluated[f"Recap!{RC.TOTAL}{r}"])
    assert _f(evaluated[f"Recap!{RC.DIRECT}{plan.recap_total_row}"]) == pytest.approx(total_direct)
    assert _f(evaluated[f"Recap!{RC.TOTAL}{plan.recap_total_row}"]) == pytest.approx(total_bid)


def test_recap_manhours_sum_the_item_shares(doc, evaluated):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    for item in wb.items:
        expected = sum(float(s.manhours) for s in wb.shares if s.item_id == item.id)
        assert _f(evaluated[f"Recap!{RC.MH}{plan.recap_rows[item.id]}"]) == pytest.approx(
            expected, abs=0.005), item.item_number


def test_total_row_formats_and_label(doc, book):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    ws, t = book["Recap"], plan.recap_total_row
    # Direct cost sums every item: say so, excluded ones included.
    assert ws[f"{RC.CODE}{t}"].value == "Total (all items, incl. excluded)"
    assert ws[f"{RC.MH}{t}"].number_format == "#,##0.0"           # hours, not money
    assert ws[f"{RC.DIRECT}{t}"].number_format.startswith("#,##0.00")
