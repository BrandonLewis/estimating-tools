"""Flat: an Excel Table whose cost column sums to the activities' own
extended costs."""
from __future__ import annotations

import pytest

from estimating_tools.heavycivil import layout, model, style
from estimating_tools.heavycivil.columns import CR, FL


def _f(v):
    return 0.0 if v in (None, "") else float(v)


def test_flat_cost_sums_to_the_activities_own_costs(doc, evaluated):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    assert plan.flat_rows
    flat = sum(_f(evaluated[f"Flat!{FL.COST}{r.row}"]) for r in plan.flat_rows)
    acts = sum(_f(evaluated[f"Cost Report!{CR.TOTAL}{plan.activity_rows[a.id].row}"])
               for a in wb.activities)
    assert flat == pytest.approx(acts, abs=0.01)


def test_flat_manhours_sum_to_the_activities_own(doc, evaluated):
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    flat = sum(_f(evaluated[f"Flat!{FL.MH}{r.row}"]) for r in plan.flat_rows)
    assert flat == pytest.approx(sum(float(a.manhours) for a in wb.activities), abs=0.01)


def test_flat_is_an_excel_table(book):
    table = book["Flat"].tables["hc_flat"]
    assert table.ref.startswith(f"{FL.ITEM}{layout.HEADER_ROW}:{FL.COST}")
