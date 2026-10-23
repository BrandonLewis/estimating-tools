"""Schedule finishes: equal to the export when fresh; moved by the change
in whole working days (on the ``_cal`` calendar) when Shifts change."""
from __future__ import annotations

from datetime import date

import pytest

from estimating_tools.estimate_spec.tests._formula_eval import evaluate
from estimating_tools.heavycivil import build, layout, model, style
from estimating_tools.heavycivil.columns import CR, SC


def _serial(d):
    return (d - date(1899, 12, 30)).days


def _ctx(doc):
    wb = model.parse(doc)
    return wb, layout.plan(wb, style.load_style())


def test_calendar_is_the_working_days_ascending(doc, book):
    wb, plan = _ctx(doc)
    ws = book["_cal"]
    days = [ws[f"A{n}"].value for n in range(1, len(plan.calendar) + 1)]
    assert days == sorted(days) == plan.calendar
    assert date(2026, 11, 26) not in days                      # the holiday
    assert all(d.weekday() < 5 for d in days)                   # Mon-Fri


def test_fresh_finishes_equal_the_export(doc, evaluated):
    wb, plan = _ctx(doc)
    assert plan.schedule_rows
    for activity_id, r in plan.schedule_rows.items():
        a = wb.activity(activity_id)
        assert float(evaluated[f"Schedule!{SC.FINISH}{r}"]) == _serial(
            date.fromisoformat(a.finish_date)), a.name
        assert float(evaluated[f"Schedule!{SC.DURATION}{r}"]) == pytest.approx(
            float(a.duration_days)), a.name


def test_more_shifts_push_the_finish_over_the_holiday(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    a = next(x for x in wb.activities if x.name == "Excavate")
    act, r = plan.activity_rows[a.id].row, plan.schedule_rows[a.id]
    book["Cost Report"][f"{CR.SHIFTS}{act}"] = 20     # 3 -> 20: 17 more working days
    ev = evaluate(book, tmp_path)
    finish = float(ev[f"Schedule!{SC.FINISH}{r}"])
    days = [_serial(d) for d in plan.calendar]
    old = days.index(_serial(date.fromisoformat(a.finish_date)))
    assert finish == days[old + 17]
    # Wed 4 Nov + 17 working days, skipping weekends and the 26 Nov holiday.
    assert finish == _serial(date(2026, 11, 30))


def test_shrinking_never_finishes_before_the_start(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    a = next(x for x in wb.activities if x.name == "Excavate")
    act, r = plan.activity_rows[a.id].row, plan.schedule_rows[a.id]
    book["Cost Report"][f"{CR.SHIFTS}{act}"] = 0.1
    ev = evaluate(book, tmp_path)
    assert float(ev[f"Schedule!{SC.FINISH}{r}"]) == _serial(date.fromisoformat(a.start_date))


def test_no_dates_renders_a_note(doc):
    doc["estimate"]["schedule"] = {"start_date": None, "working_weekdays": None, "holidays": []}
    for a in doc["activities"]:
        a["start_date"] = a["end_date"] = a["finish_date"] = None
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    assert "No schedule dates" in str(book["Schedule"][f"{SC.NAME}5"].value)
    assert book["_cal"]["A1"].value is None


def test_a_counted_activity_finishes_as_exported_when_fresh(doc, tmp_path):
    """``duration_days`` is per pass (``Assembly.duration_days``); BidSheet.ai
    dates the activity over ``duration_days x count`` working days
    (``estimate_task_rollup``). Excavate run twice: 3 shifts x 2 = 6 working
    days from Mon 2 Nov, so it ends (exclusive) Tue 10 Nov, finishing Mon 9."""
    excavate = next(a for a in doc["activities"] if a["name"] == "Excavate")
    excavate["count"] = 2
    excavate["end_date"], excavate["finish_date"] = "2026-11-10", "2026-11-09"
    assert excavate["duration_days"] == "3.00"                  # per pass
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    wb, plan = _ctx(doc)
    r = plan.schedule_rows[excavate["id"]]
    ev = evaluate(book, tmp_path)
    assert float(ev[f"Schedule!{SC.FINISH}{r}"]) == _serial(date(2026, 11, 9))
    assert float(ev[f"Schedule!{SC.DURATION}{r}"]) == pytest.approx(6.0)
    ws = book["Checks"]
    rows = [n for n in range(5, ws.max_row + 1)
            if ws[f"A{n}"].value == "schedule" and ws[f"C{n}"].value == "Excavate"]
    assert rows
    for n in rows:
        assert ev[f"Checks!I{n}"] == "OK"


def test_a_count_edit_moves_the_bar(doc, book, tmp_path):
    """Count is a live multiplier: Excavate 1 -> 2 passes is 3 more working
    days (Wed 4 Nov -> Mon 9 Nov)."""
    wb, plan = _ctx(doc)
    a = next(x for x in wb.activities if x.name == "Excavate")
    act, r = plan.activity_rows[a.id].row, plan.schedule_rows[a.id]
    book["Cost Report"][f"{CR.COUNT}{act}"] = 2
    ev = evaluate(book, tmp_path)
    assert float(ev[f"Schedule!{SC.FINISH}{r}"]) == _serial(date(2026, 11, 9))


def test_a_non_working_start_still_moves_the_finish(doc, tmp_path):
    """The calendar starts a week before the earliest start, so a start on
    a non-working day (Sun 1 Nov) still finds its place on it."""
    excavate = next(a for a in doc["activities"] if a["name"] == "Excavate")
    excavate["start_date"] = "2026-11-01"
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    wb, plan = _ctx(doc)
    assert plan.calendar[0] <= date(2026, 11, 1)
    a = wb.activity(excavate["id"])
    act, r = plan.activity_rows[a.id].row, plan.schedule_rows[a.id]
    book["Cost Report"][f"{CR.SHIFTS}{act}"] = 4
    ev = evaluate(book, tmp_path)
    assert float(ev[f"Schedule!{SC.FINISH}{r}"]) == _serial(date(2026, 11, 5))


def test_an_absurd_increase_stops_on_the_last_calendar_day(doc, book, tmp_path):
    """Past the calendar's tail the finish clamps to its last day -- never
    silently falls back to the export finish."""
    wb, plan = _ctx(doc)
    a = next(x for x in wb.activities if x.name == "Excavate")
    act, r = plan.activity_rows[a.id].row, plan.schedule_rows[a.id]
    book["Cost Report"][f"{CR.SHIFTS}{act}"] = 100000
    ev = evaluate(book, tmp_path)
    assert float(ev[f"Schedule!{SC.FINISH}{r}"]) == _serial(plan.calendar[-1])


def test_a_year_of_extra_shifts_fits_the_calendar(doc, book, tmp_path):
    wb, plan = _ctx(doc)
    a = next(x for x in wb.activities if x.name == "Excavate")
    act, r = plan.activity_rows[a.id].row, plan.schedule_rows[a.id]
    book["Cost Report"][f"{CR.SHIFTS}{act}"] = 3 + 250
    ev = evaluate(book, tmp_path)
    days = [_serial(d) for d in plan.calendar]
    old = days.index(_serial(date.fromisoformat(a.finish_date)))
    assert float(ev[f"Schedule!{SC.FINISH}{r}"]) == days[old + 250]


def test_export_multiplier_is_shared_by_the_cost_report_and_schedule():
    from estimating_tools.heavycivil.sheets import cost_report, schedule
    assert not hasattr(cost_report, "_export_multiplier")
    assert schedule.export_multiplier is cost_report.export_multiplier
