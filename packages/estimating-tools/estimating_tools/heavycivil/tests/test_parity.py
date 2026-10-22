"""Every live formula against BidSheet.ai's own figure in the fixture.

The fixture was produced by BidSheet.ai's ``build_workbook``
(Projects/tests/test_heavycivil_fixture.py), so a failure here is a formula
that does not reproduce BidSheet.ai's rule."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest

from estimating_tools.estimate_spec.tests._formula_eval import evaluate
from estimating_tools.heavycivil import build, layout, model, style
from estimating_tools.heavycivil.columns import CK, CR, CW


@pytest.fixture
def ctx(doc, book, evaluated):
    wb = model.parse(doc)
    return wb, layout.plan(wb, style.load_style()), evaluated


def _num(value):
    return 0.0 if value in (None, "") else float(value)


def test_every_resource_cost_matches(ctx):
    wb, plan, ev = ctx
    for res in wb.resources:
        r = plan.resource_rows[res.id].row
        assert _num(ev[f"Cost Report!{CR.H2}{r}"]) == pytest.approx(float(res.cost), abs=0.005), \
            res.name


def test_every_activity_cost_and_manhours_match(ctx):
    """Cost is the in-bid part (own cost x the fraction of its shares the
    payload carries); man-hours stay the activity's own, whole."""
    wb, plan, ev = ctx
    for a in wb.activities:
        r = plan.activity_rows[a.id].row
        assert _num(ev[f"Cost Report!{CR.MH}{r}"]) == pytest.approx(
            float(a.manhours), abs=0.005), a.name
        f = _num(ev[f"Cost Report!{CR.H1}{r}"])
        if f == 0:
            continue
        assert _num(ev[f"Cost Report!{CR.TOTAL}{r}"]) * f == pytest.approx(
            float(a.cost), abs=0.005), a.name
        for kind, col in CR.SPLIT:
            expected = float(a.cost_split.get(kind) or 0)
            assert _num(ev[f"Cost Report!{col}{r}"]) * f == pytest.approx(expected, abs=0.005),                 (a.name, kind)


def _exclude_b3(doc):
    """Mark item B3 excluded the way BidSheet.ai exports it: its shares are
    dropped and each activity's cost/cost_split sums only the shares left
    (man-hours stay whole)."""
    b3 = next(i for i in doc["items"] if i["item_number"] == "B3")
    b3["scope"] = "excluded"
    doc["shares"] = [s for s in doc["shares"] if s["item_id"] != b3["id"]]
    for a in doc["activities"]:
        kept = [s for s in doc["shares"] if s["activity_id"] == a["id"]]
        total = sum(float(s["cost"]) for s in kept)
        if a["name"] == "Pour":
            assert [s["cost"] for s in kept] == ["542.38"]
            a["cost"], a["cost_split"] = "542.38", {"material": "542.38"}
        elif a["name"] == "Finish":
            assert not kept
            a["cost"], a["cost_split"] = "0", {}
        else:
            assert float(a["cost"]) == pytest.approx(total)
    # The estimate's bid figures as BidSheet.ai exports them with B3 out
    # (recalculate_totals / bid_totals.compute, by hand): TEC 12 + M1 =
    # 14657.40 + 100.00; markup 10% + 250; B3's calculate_total (20 x
    # 166.88) joins the excluded cost; the factor reprices 12 and A1.
    e = doc["estimate"]
    e["totals"].update(total_estimated_cost="14757.40", direct_cost="14757.40",
                       markup_total="1725.74", bid_total="16491.40")
    e["bid_factor"] = e["live_bid_factor"] = "1.1169406535"
    e["excluded_cost"] = "3437.60"
    for bt in e["bid_totals"]:
        bt["amount"] = {"Base Bid": "16491.40", "Alternate 1": "558.45"}[bt["name"]]
    prices = {"12": ("1637.14", "16371.40"), "A1": ("111.69", "558.45"), "B3": (None, None)}
    for item in doc["items"]:
        if item["item_number"] in prices:
            item["bid_unit_price"], item["bid_total"] = prices[item["item_number"]]
    return b3


def test_shares_to_an_excluded_item_leave_checks_ok(doc, tmp_path):
    _exclude_b3(doc)
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    ev = evaluate(book, tmp_path)
    pour = next(a for a in wb.activities if a.name == "Pour")
    r = plan.activity_rows[pour.id].row
    assert _num(ev[f"Cost Report!{CR.H1}{r}"]) == pytest.approx(0.5423728813559322)
    assert _num(ev[f"Cost Report!{CR.TOTAL}{r}"]) == pytest.approx(1000.01, abs=0.005)
    assert _num(ev["Checks!E3"]) == 0
    statuses = {}
    ws = book["Checks"]
    n = layout.FIRST_ROW
    while ws[f"{CK.KIND}{n}"].value:
        statuses.setdefault((ws[f"{CK.DESC}{n}"].value, ws[f"{CK.MEASURE}{n}"].value),
                            ev[f"Checks!{CK.STATUS}{n}"])
        n += 1
    assert statuses[("Pour", "cost")] == "OK"
    assert statuses[("Finish", "cost")] == "export"
    assert statuses[("Finish", "man-hours")] == "OK"


def test_every_crew_rate_matches(ctx):
    wb, plan, ev = ctx
    for crew in wb.crews:
        r = plan.crew_rows[crew.id].row
        assert _num(ev[f"Crews!{CW.RATE}{r}"]) == pytest.approx(float(crew.hourly_rate), abs=0.005)
        for m in crew.members:
            mr = plan.member_rows[m.id].row
            assert _num(ev[f"Crews!{CW.EFFECTIVE}{mr}"]) == pytest.approx(
                float(m.effective_hourly_rate), abs=0.005)


def test_every_included_item_unit_price_and_cost_match(ctx):
    wb, plan, ev = ctx
    split = Counter(s.activity_id for s in wb.shares)
    for item in wb.items:
        if item.scope == "excluded":
            continue
        r = plan.item_rows[item.id].row
        n_split = sum(1 for s in wb.shares if s.item_id == item.id and split[s.activity_id] > 1)
        tol = 0.005 + 0.01 * n_split
        expected_cup = float(item.calculated_unit_price or 0)
        assert _num(ev[f"Cost Report!{CR.H4}{r}"]) == pytest.approx(expected_cup, abs=tol), \
            item.item_number
        price = (item.estimated_unit_price if item.estimated_unit_price is not None
                 else (item.calculated_unit_price or 0))
        qty = float(item.quantity or 0)
        expected_cost = float(price) * qty  # calculate_total, not the stored total
        assert _num(ev[f"Cost Report!{CR.TOTAL}{r}"]) == pytest.approx(
            expected_cost, abs=0.005 + (0.01 * qty if n_split else 0)), item.item_number


def test_checks_sheet_reads_all_ok(ctx, book):
    _, _, ev = ctx
    assert _num(ev["Checks!E3"]) == 0
    assert _num(ev["Checks!G3"]) == 0
    ws = book["Checks"]
    r = layout.FIRST_ROW
    kinds = Counter()
    while ws[f"{CK.KIND}{r}"].value in ("activity", "resource", "item", "crew", "estimate",
                                        "bid item", "bid total", "schedule", "element"):
        assert ev[f"Checks!{CK.STATUS}{r}"] in ("OK", "export"), r
        kinds[ws[f"{CK.KIND}{r}"].value] += 1
        r += 1
    assert not ws[f"{CK.KIND}{r}"].value or "warnings" in ws[f"{CK.KIND}{r}"].value
    assert kinds["estimate"] == 4 and kinds["bid total"] == 2 and kinds["schedule"] == 2
    assert kinds["bid item"] == 2 * len(ctx[0].items)


def test_missing_crew_uses_export_figures(doc, tmp_path):
    """A library crew the payload omits: the activity is priced from
    BidSheet.ai's per-unit figures as of export, times the live multiplier."""
    doc["crews"] = [c for c in doc["crews"]
                    if not (c["scope"] == "library" and c["name"] == "Pour crew")]
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    ev = evaluate(book, tmp_path)
    finish = next(a for a in wb.activities if a.name == "Finish")
    assert finish.crew_id is not None and wb.crew(finish.crew_id) is None
    r = plan.activity_rows[finish.id].row
    assert _num(ev[f"Cost Report!{CR.TOTAL}{r}"]) == pytest.approx(2880, abs=0.005)
    assert _num(ev[f"Cost Report!{CR.MH}{r}"]) == pytest.approx(48, abs=0.005)
    assert _num(ev["Checks!E3"]) == 0


def test_missing_crew_follows_a_shifts_edit(doc, tmp_path):
    """The export figures are per shift, so the activity's Shifts stay live."""
    doc["crews"] = [c for c in doc["crews"]
                    if not (c["scope"] == "library" and c["name"] == "Pour crew")]
    wb = model.parse(doc)
    plan = layout.plan(wb, style.load_style())
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    finish = next(a for a in wb.activities if a.name == "Finish")
    r = plan.activity_rows[finish.id].row
    book["Cost Report"][f"{CR.SHIFTS}{r}"] = float(finish.duration_shifts) * 2
    ev = evaluate(book, tmp_path)
    assert _num(ev[f"Cost Report!{CR.LAB}{r}"]) == pytest.approx(5760, abs=0.005)
    assert _num(ev[f"Cost Report!{CR.MH}{r}"]) == pytest.approx(96, abs=0.005)


def test_fixture_exercises_every_rule(doc):
    """Guards the fixture itself: regenerate it if BidSheet.ai changes shape."""
    wb = model.parse(doc)
    assert any(a.crew_id and a.duration_shifts is not None for a in wb.activities)
    assert any(r.labor_cost_basis == "flat" for r in wb.resources)
    assert any(r.time_value is not None for r in wb.resources)
    assert any(r.burden_percentage for r in wb.resources)
    assert any(a.count > 1 and wb.children(a.id) for a in wb.activities)
    assert any(a.steps for a in wb.activities)
    assert any(c.scope == "library" for c in wb.crews)
    assert any(i.estimated_unit_price is not None for i in wb.items)
    assert any(i.scope == "excluded" for i in wb.items)
    assert max(Counter(s.activity_id for s in wb.shares).values()) > 1


def _checks(book, ev=None):
    """{(kind, description, measure): (row, status)} over the Checks rows."""
    ws, out, n = book["Checks"], {}, layout.FIRST_ROW
    while ws[f"{CK.KIND}{n}"].value:
        out.setdefault((ws[f"{CK.KIND}{n}"].value, ws[f"{CK.DESC}{n}"].value,
                        ws[f"{CK.MEASURE}{n}"].value),
                       (n, ev[f"Checks!{CK.STATUS}{n}"] if ev else None))
        n += 1
    return out


def test_stepped_activity_shifts_check_ok_when_fresh(book, evaluated):
    row, status = _checks(book, evaluated)[("activity", "Prep", "shifts")]
    assert status == "OK"
    assert book["Checks"][f"{CK.TOL}{row}"].value == Decimal("0.005")
    assert ("activity", "Walls", "shifts") not in _checks(book)  # unstepped: no shifts row


def test_stale_step_stamp_reads_diff(doc, tmp_path):
    """BidSheet.ai does not always restamp duration_shifts (bulk-created
    steps, an hours_per_shift edit): the live step formula then disagrees
    with the stored figure, and Checks says so."""
    prep = next(a for a in doc["activities"] if a["name"] == "Prep")
    prep["duration_shifts"] = "3.00"
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    ev = evaluate(book, tmp_path)
    assert _checks(book, ev)[("activity", "Prep", "shifts")][1] == "DIFF"
    assert _num(ev["Checks!E3"]) == 1


def test_item_cost_tolerance_uses_the_absolute_quantity(doc):
    concrete = next(i for i in doc["items"] if i["description"] == "Concrete")
    concrete["quantity"] = "-10"
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    row, _ = _checks(book)[("item", "Concrete", "cost")]
    assert book["Checks"][f"{CK.TOL}{row}"].value == Decimal("0.105")


def test_near_one_in_bid_fraction_is_exactly_one(doc):
    from estimating_tools.heavycivil.sheets.cost_report import in_bid_fraction
    pour = next(a for a in doc["activities"] if a["name"] == "Pour")
    a, b = [s for s in doc["shares"] if s["activity_id"] == pour["id"]]
    a["fraction"], b["fraction"] = "0.5", "0.4999999999999999999"
    wb = model.parse(doc)
    f = in_bid_fraction(wb, wb.activity(pour["id"]))
    assert f == 1 and str(f) == "1"
    plan = layout.plan(wb, style.load_style())
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    assert book["Cost Report"][f"{CR.H1}{plan.activity_rows[pour['id']].row}"].value == 1
    row, _ = _checks(book)[("activity", "Pour", "cost")]
    assert "$AF$" not in book["Checks"][f"{CK.EXCEL}{row}"].value


def _notes(book):
    ws = book["Checks"]
    return [ws[f"{CK.DESC}{r}"].value for r in range(1, ws.max_row + 1)
            if ws[f"{CK.DESC}{r}"].value]


def test_missing_crew_without_shifts_is_warned(doc):
    doc["crews"] = [c for c in doc["crews"]
                    if not (c["scope"] == "library" and c["name"] == "Pour crew")]
    plain = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    assert not [n for n in _notes(plain) if "no shifts at export" in n]
    finish = next(a for a in doc["activities"] if a["name"] == "Finish")
    finish["duration_shifts"] = None
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    notes = [n for n in _notes(book) if "no shifts at export" in n]
    assert notes == [("Finish: crew not in this export and no shifts at export: typing Shifts "
                      "prices labour at 0 -- re-export")]
