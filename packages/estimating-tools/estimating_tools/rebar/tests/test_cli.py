"""est-rebar CLI: schedule + develop subcommands, happy paths and the house
clean-failure style (print one line, rc 1)."""
from __future__ import annotations

import json

import pytest
import yaml

from estimating_tools.rebar.cli import main
from estimating_tools.rebar.schedule import DEFAULT_WASTE_FACTOR
from estimating_tools.takeoff.model import CanonicalTakeoff

BARS = {
    "title": "Footing F1",
    "marks": [
        {"mark": "A1", "size": 5, "count": 20, "legs_in": [96.0, 24.0], "hooks": ["90"]},
        {"mark": "B1", "size": 4, "count": 5, "legs_in": [36.0, 12.0, 12.0]},
    ],
}


def _write_bars(tmp_path, data=None):
    path = tmp_path / "bars.yaml"
    path.write_text(yaml.safe_dump(data if data is not None else BARS), encoding="utf-8")
    return path


# --- schedule: happy paths ---------------------------------------------------

def test_schedule_writes_markdown(tmp_path):
    bars = _write_bars(tmp_path)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 0

    md_path = tmp_path / "footing-f1.md"
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "A1" in text
    assert "Total" in text


def test_schedule_xlsx_flag(tmp_path):
    pytest.importorskip("openpyxl")
    bars = _write_bars(tmp_path)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path), "--xlsx"])
    assert rc == 0
    assert (tmp_path / "footing-f1.xlsx").exists()


def test_schedule_xlsx_missing_openpyxl_gives_clean_error(tmp_path, monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("no module named openpyxl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    bars = _write_bars(tmp_path)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path), "--xlsx"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "excel" in out


def test_schedule_takeoff_round_trips_through_canonical_takeoff(tmp_path):
    bars = _write_bars(tmp_path)
    out_json = tmp_path / "takeoff.json"
    rc = main([
        "schedule", str(bars), "--out-dir", str(tmp_path),
        "--takeoff", str(out_json), "--organization-id", "42",
        "--cost-code", "03-2100", "--item-number", "12",
        "--schedule", "F1", "--project-ref", "P-1",
    ])
    assert rc == 0
    assert out_json.exists()

    takeoff = CanonicalTakeoff.from_json(out_json.read_text(encoding="utf-8"))
    assert takeoff.organization_id == 42
    assert takeoff.project_ref == "P-1"
    assert len(takeoff.rows) == 1

    row = takeoff.rows[0]
    assert row.kind == "quantity"
    assert row.unit == "LBS"
    assert row.cost_code == "03-2100"
    assert row.item_number == "12"
    assert row.schedule == "F1"

    # Hand-recompute the schedule total the same way BarSchedule does, to
    # verify the CLI wrote the waste-applied total (not the raw weight).
    from estimating_tools.rebar.model import BarSize
    from estimating_tools.rebar.schedule import BarMark, BarSchedule

    sched = BarSchedule(title="Footing F1", marks=[
        BarMark(mark="A1", size=BarSize(5), count=20, legs_in=[96.0, 24.0], hooks=["90"]),
        BarMark(mark="B1", size=BarSize(4), count=5, legs_in=[36.0, 12.0, 12.0]),
    ])
    expected_qty = round(sched.total_weight_lb * DEFAULT_WASTE_FACTOR, 1)
    assert row.quantity == pytest.approx(expected_qty)


# --- schedule: clean failures ------------------------------------------------

def test_schedule_missing_file(tmp_path, capsys):
    rc = main(["schedule", str(tmp_path / "missing.yaml"), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "no such file" in capsys.readouterr().out


def test_schedule_invalid_yaml(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("title: [unterminated", encoding="utf-8")
    rc = main(["schedule", str(bad), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "invalid YAML" in capsys.readouterr().out


def test_schedule_not_a_mapping(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    rc = main(["schedule", str(bad), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "mapping" in capsys.readouterr().out


def test_schedule_marks_not_a_list(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"title": "T", "marks": "nope"}), encoding="utf-8")
    rc = main(["schedule", str(bad), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "marks" in capsys.readouterr().out


def test_schedule_bad_hook_names_the_mark(tmp_path, capsys):
    bad_bars = {
        "title": "Footing F1",
        "marks": [
            {"mark": "S1", "size": 9, "count": 2, "legs_in": [24.0], "hooks": ["stirrup90"]},
        ],
    }
    bars = _write_bars(tmp_path, bad_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "S1" in out


def test_schedule_duplicate_mark(tmp_path, capsys):
    dup_bars = {
        "title": "Footing F1",
        "marks": [
            {"mark": "A1", "size": 5, "count": 20, "legs_in": [96.0]},
            {"mark": "A1", "size": 4, "count": 1, "legs_in": [12.0]},
        ],
    }
    bars = _write_bars(tmp_path, dup_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "duplicate mark" in capsys.readouterr().out


def test_schedule_bad_bar_size(tmp_path, capsys):
    bad_bars = {
        "title": "Footing F1",
        "marks": [{"mark": "A1", "size": 2, "count": 1, "legs_in": [24.0]}],
    }
    bars = _write_bars(tmp_path, bad_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "unknown bar size" in capsys.readouterr().out


def test_schedule_missing_size_names_the_mark(tmp_path, capsys):
    bad_bars = {
        "title": "Footing F1",
        "marks": [
            {"mark": "B2", "count": 2, "legs_in": [24.0]},
        ],
    }
    bars = _write_bars(tmp_path, bad_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "B2" in capsys.readouterr().out


def test_schedule_non_numeric_size_names_the_mark(tmp_path, capsys):
    bad_bars = {
        "title": "Footing F1",
        "marks": [
            {"mark": "B2", "size": "#5", "count": 2, "legs_in": [24.0]},
        ],
    }
    bars = _write_bars(tmp_path, bad_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "B2" in capsys.readouterr().out


def test_schedule_scalar_legs_in_names_the_mark(tmp_path, capsys):
    bad_bars = {
        "title": "Footing F1",
        "marks": [
            {"mark": "B2", "size": 5, "count": 2, "legs_in": 24.0},
        ],
    }
    bars = _write_bars(tmp_path, bad_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "B2" in capsys.readouterr().out


def test_schedule_fractional_count_is_rejected(tmp_path, capsys):
    bad_bars = {
        "title": "Footing F1",
        "marks": [
            {"mark": "B2", "size": 5, "count": 2.5, "legs_in": [24.0]},
        ],
    }
    bars = _write_bars(tmp_path, bad_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "whole number" in out
    assert "B2" in out


def test_schedule_non_mapping_mark_names_the_index(tmp_path, capsys):
    bad_bars = {
        "title": "Footing F1",
        "marks": ["not a mapping"],
    }
    bars = _write_bars(tmp_path, bad_bars)
    rc = main(["schedule", str(bars), "--out-dir", str(tmp_path)])
    assert rc == 1
    assert "index 0" in capsys.readouterr().out


def test_schedule_takeoff_without_organization_id(tmp_path, capsys):
    bars = _write_bars(tmp_path)
    rc = main([
        "schedule", str(bars), "--out-dir", str(tmp_path),
        "--takeoff", str(tmp_path / "out.json"),
    ])
    assert rc == 1
    assert "--organization-id" in capsys.readouterr().out
    assert not (tmp_path / "out.json").exists()


# --- develop ------------------------------------------------------------------

def test_develop_prints_ld_and_lap(capsys):
    rc = main(["develop", "--size", "5", "--fc", "4000"])
    assert rc == 0
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert lines[0].startswith("ld = ")
    assert lines[0].endswith(" in")
    assert lines[1].startswith("lap (Class B) = ")
    assert lines[1].endswith(" in")


def test_develop_lap_class_a_and_flags(capsys):
    rc = main([
        "develop", "--size", "8", "--fc", "4000", "--fy", "60000",
        "--top-bar", "--epoxy", "--lightweight", "--lap", "A",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lap (Class A) = " in out


def test_develop_bad_size(capsys):
    rc = main(["develop", "--size", "2", "--fc", "4000"])
    assert rc == 1
    assert "unknown bar size" in capsys.readouterr().out


def test_develop_bad_fc(capsys):
    rc = main(["develop", "--size", "5", "--fc", "0"])
    assert rc == 1
    assert "fc_psi" in capsys.readouterr().out
