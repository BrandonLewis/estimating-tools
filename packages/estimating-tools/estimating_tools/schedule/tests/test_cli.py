import json
from estimating_tools.schedule import cli


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_costload_json_output(tmp_path, capsys):
    sched = _write(tmp_path, "s.json", {
        "name": "S", "work_weekdays": [0, 1, 2, 3, 4], "holidays": [],
        "tasks": [{"id": "t1", "name": "Pour", "start": "2026-08-10",
                   "finish": "2026-08-14", "bid_item_codes": ["A"]}]})
    costs = _write(tmp_path, "c.json", {"A": {"cost": 10000.0, "labor_hours": 400.0}})
    assert cli.main(["costload", "--schedule", sched, "--costs", costs,
                     "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert round(out["total_cost"], 2) == 10000.0
    assert out["peak_period"] == "2026-W33"


def test_costload_reports_coverage_to_stderr(tmp_path, capsys):
    sched = _write(tmp_path, "s.json", {
        "name": "S", "tasks": [{"id": "t1", "name": "x", "start": "2026-08-10",
                                "finish": "2026-08-10", "bid_item_codes": ["A"]}]})
    costs = _write(tmp_path, "c.json", {"A": {"cost": 1.0, "labor_hours": None},
                                        "B": {"cost": 700.0, "labor_hours": 5.0}})
    assert cli.main(["costload", "--schedule", sched, "--costs", costs, "--json"]) == 0
    err = capsys.readouterr().err
    assert "unloaded cost" in err.lower()
    assert "B" in err  # priced, no task


def test_costload_malformed_costs_is_clean_error(tmp_path, capsys):
    sched = _write(tmp_path, "s.json", {
        "name": "S", "tasks": [{"id": "t1", "name": "x", "start": "2026-08-10",
                                "finish": "2026-08-10", "bid_item_codes": ["A"]}]})
    costs = _write(tmp_path, "c.json", {"A": {"labor_hours": 5}})  # missing 'cost'
    # a clean rc=1 + stderr message, never a traceback
    assert cli.main(["costload", "--schedule", sched, "--costs", costs, "--json"]) == 1
    assert "error:" in capsys.readouterr().err.lower()
