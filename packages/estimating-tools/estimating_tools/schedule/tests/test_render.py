from estimating_tools.schedule.costload import LoadedSchedule, PeriodLoad
from estimating_tools.schedule import render


def _loaded():
    wk = PeriodLoad(period="2026-W33", start="2026-08-10", end="2026-08-14",
                    cost=10000.0, cumulative_cost=10000.0, labor_hours=400.0,
                    avg_workers=10.0, peak_workers=10.0)
    return LoadedSchedule(name="S", work_hours_per_day=8.0, total_cost=10000.0,
                          total_labor_hours=400.0, peak_workers=10.0,
                          peak_period="2026-W33", by_week=[wk], by_month=[wk],
                          by_task={"t1": {"cost": 10000.0, "labor_hours": 400.0}})


def test_render_has_cashflow_and_manpower_and_summary():
    md = render.render(_loaded(), bucket="week")
    assert "Cash Flow" in md and "Manpower" in md
    assert "2026-W33" in md
    assert "$10,000" in md                      # period cost
    assert "10" in md                           # peak workers
    assert "Peak crew" in md                    # summary line


def test_to_csv_is_period_rows():
    csv = render.to_csv(_loaded(), bucket="week")
    lines = csv.strip().splitlines()
    assert lines[0] == "period,start,end,cost,cumulative_cost,labor_hours,avg_workers,peak_workers"
    assert lines[1].startswith("2026-W33,2026-08-10,2026-08-14,10000.0")
