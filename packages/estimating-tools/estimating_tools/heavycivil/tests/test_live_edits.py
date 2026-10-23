"""Edits move the totals the way BidSheet.ai's rules say they should."""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.tests._formula_eval import evaluate as _evaluate
from estimating_tools.heavycivil import layout, model, style
from estimating_tools.heavycivil.columns import CR, CW


def _ctx(doc):
    wb = model.parse(doc)
    return wb, layout.plan(wb, style.load_style())


def evaluate(book, path):
    """Evaluate into ``path`` (made if missing), so before/after saves differ."""
    path.mkdir(parents=True, exist_ok=True)
    return _evaluate(book, path)


def _f(v):
    return 0.0 if v in (None, "") else float(v)


def test_crew_count_edit_moves_crew_rate_and_activity(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    crew = next(c for c in wb.crews if c.scope == "estimate")
    member = next(m for m in crew.members if m.hourly_rate_override is not None)
    a = next(x for x in wb.activities if x.crew_id == crew.id)
    before = evaluate(book, tmp_path / "a")
    book["Crews"][f"{CW.COUNT}{plan.member_rows[member.id].row}"] = float(member.count) + 1
    after = evaluate(book, tmp_path / "b")
    crew_row, act_row = plan.crew_rows[crew.id].row, plan.activity_rows[a.id].row
    assert _f(after[f"Crews!{CW.RATE}{crew_row}"]) == pytest.approx(
        _f(before[f"Crews!{CW.RATE}{crew_row}"]) + float(member.hourly_rate_override))
    assert _f(after[f"Cost Report!{CR.TOTAL}{act_row}"]) > _f(
        before[f"Cost Report!{CR.TOTAL}{act_row}"])


def test_production_rate_edit_scales_production_labor(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    a = next(x for x in wb.activities if x.production_rate is not None)
    r = plan.activity_rows[a.id].row
    before = evaluate(book, tmp_path / "a")
    book["Cost Report"][f"{CR.PROD}{r}"] = float(a.production_rate) * 2
    after = evaluate(book, tmp_path / "b")
    assert _f(after[f"Cost Report!{CR.LAB}{r}"]) > _f(before[f"Cost Report!{CR.LAB}{r}"])


def test_unit_cost_edit_moves_item_cost(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    item = next(i for i in wb.items if i.item_number == "12")
    res = next(x for x in wb.resources if x.component_type == "equipment")
    before = evaluate(book, tmp_path / "a")
    book["Cost Report"][f"{CR.UCOST}{plan.resource_rows[res.id].row}"] = float(res.unit_cost) + 10
    after = evaluate(book, tmp_path / "b")
    item_row = plan.item_rows[item.id].row
    assert _f(after[f"Cost Report!{CR.TOTAL}{item_row}"]) > _f(
        before[f"Cost Report!{CR.TOTAL}{item_row}"])


def test_manual_price_wins_over_breakdown(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    item = next(i for i in wb.items if i.item_number == "12")
    r = plan.item_rows[item.id].row
    book["Cost Report"][f"{CR.UCOST}{r}"] = 7.5
    ev = evaluate(book, tmp_path)
    assert _f(ev[f"Cost Report!{CR.TOTAL}{r}"]) == pytest.approx(7.5 * float(item.quantity))


def test_shifts_cleared_falls_back_to_resource_labor(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    a = next(x for x in wb.activities if x.crew_id and x.duration_shifts is not None
             and wb.crew(x.crew_id))
    r = plan.activity_rows[a.id].row
    book["Cost Report"][f"{CR.SHIFTS}{r}"] = None
    ev = evaluate(book, tmp_path)
    span = plan.resource_span[a.id]
    labor_lines = 0.0 if span is None else sum(
        _f(ev[f"Cost Report!{CR.LAB}{n}"]) for n in range(span[0], span[1] + 1))
    assert _f(ev[f"Cost Report!{CR.LAB}{r}"]) == pytest.approx(labor_lines * a.count)


def _prep(wb, plan):
    a = next(x for x in wb.activities if x.name == "Prep")
    return a, plan.activity_rows[a.id].row, plan.step_rows[a.steps[0].id].row


def test_stepped_activity_shifts_are_a_live_formula(doc, book):
    wb, plan = _ctx(doc)
    _, r, _ = _prep(wb, plan)
    cell = book["Cost Report"][f"{CR.SHIFTS}{r}"]
    assert isinstance(cell.value, str) and cell.value.startswith("=")
    input_fill = "FF" + style.load_style().tokens["fills"]["input"]
    assert cell.fill.fgColor.rgb != input_fill


@pytest.mark.parametrize("duration, unit, shifts", [
    (4, "DAYS", 4.0),
    (4, "HOURS", 0.5),          # hours / the activity's hours per shift (8)
    (1, "HOURS", 0.12),         # 0.125 rounds half-even, as Decimal.quantize does
    (3, "HOURS", 0.38),         # 0.375 -> 0.38 (half-even)
    (1.5, None, 1.5),           # a blank unit is DAYS
])
def test_step_duration_edit_moves_shifts(doc, book, tmp_path, duration, unit, shifts):
    wb, plan = _ctx(doc)
    _, r, step = _prep(wb, plan)
    ws = book["Cost Report"]
    ws[f"{CR.QTY}{step}"] = duration
    ws[f"{CR.UNIT}{step}"] = unit
    ev = evaluate(book, tmp_path)
    assert _f(ev[f"Cost Report!{CR.SHIFTS}{r}"]) == pytest.approx(shifts)


def test_step_hours_use_eight_when_hours_per_shift_blank(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    _, r, step = _prep(wb, plan)
    ws = book["Cost Report"]
    ws[f"{CR.HPS}{r}"] = None
    ws[f"{CR.QTY}{step}"] = 4
    ws[f"{CR.UNIT}{step}"] = "HOURS"
    ev = evaluate(book, tmp_path)
    assert _f(ev[f"Cost Report!{CR.SHIFTS}{r}"]) == pytest.approx(0.5)


def test_negative_quantity_prices_like_calculate_total(doc, book, tmp_path):
    """Only a blank or zero quantity zeroes the cost; a negative one still
    multiplies the manual price (the calculated price is blank below zero)."""
    wb, plan = _ctx(doc)
    m1 = next(i for i in wb.items if i.item_number == "M1")
    twelve = next(i for i in wb.items if i.item_number == "12")
    ws = book["Cost Report"]
    ws[f"{CR.QTY}{plan.item_rows[m1.id].row}"] = -4
    ws[f"{CR.QTY}{plan.item_rows[twelve.id].row}"] = -2
    ev = evaluate(book, tmp_path)
    assert _f(ev[f"Cost Report!{CR.TOTAL}{plan.item_rows[m1.id].row}"]) == pytest.approx(-100)
    assert _f(ev[f"Cost Report!{CR.TOTAL}{plan.item_rows[twelve.id].row}"]) == 0


def _check_rows(book, kind):
    ws = book["Checks"]
    r, out = layout.FIRST_ROW, {}
    while ws[f"A{r}"].value:
        if ws[f"A{r}"].value == kind:
            out[ws[f"B{r}"].value, ws[f"C{r}"].value] = r
        r += 1
    return out


def test_element_quantities_read_ok_until_edited(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    rows = _check_rows(book, "element")
    assert len(rows) == sum(len(e.quantities) for e in wb.elements)
    ev = evaluate(book, tmp_path / "a")
    assert all(ev[f"Checks!I{r}"] == "OK" for r in rows.values())
    assert _f(ev["Checks!G3"]) == 0
    assert book["Checks"]["F3"].value == "Edits needing re-export:"

    wall_a = next(e for e in wb.elements if e.name == "Wall A")
    wall_b = next(e for e in wb.elements if e.name == "Wall B")
    ws = book["Cost Report"]
    ws[f"{CR.QTY}{plan.quantity_rows[(wall_a.id, 'concrete_cy')].row}"] = 70
    ws[f"{CR.QTY}{plan.quantity_rows[(wall_b.id, 'concrete_cy')].row}"] = None
    ev = evaluate(book, tmp_path / "b")
    for r in rows.values():
        assert ev[f"Checks!I{r}"] == "CHANGED -- re-export to reweight"
    assert _f(ev["Checks!G3"]) == 2
    assert _f(ev["Checks!E3"]) == 0  # an override edit is not a cost DIFF
