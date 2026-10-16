"""Smoke tests for estimating_tools.schedule.gantt_to_ganttwarrior."""
from __future__ import annotations

import importlib
import json
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest


def test_module_imports_and_has_main():
    mod = importlib.import_module("estimating_tools.schedule.gantt_to_ganttwarrior")
    assert hasattr(mod, "main")


def _build_minimal_workbook(path: Path) -> Path:
    """Create a minimal Gantt workbook that the converter can parse."""
    wb = openpyxl.Workbook()

    # --- Settings sheet ---
    ws_settings = wb.active
    ws_settings.title = "Settings"
    ws_settings.append(["Project Start Date:", datetime(2026, 1, 5)])
    ws_settings.append(["Project Name:", "Smoke Test Project"])
    ws_settings.append(["Project Number:", "P-001"])
    ws_settings.append(["Work Days/Week:", 5])
    ws_settings.append(["Skip Holidays:", "No"])
    # HOLIDAYS sentinel — no holidays, so just add the label
    ws_settings.append(["HOLIDAYS"])

    # --- Schedule sheet ---
    # Header row is row 4; data starts at row 5.
    ws_sched = wb.create_sheet("Schedule")
    # Rows 1-3 are blank spacers in the real template
    ws_sched.append([])  # row 1
    ws_sched.append([])  # row 2
    ws_sched.append([])  # row 3
    # Row 4: header (cols: WBS, Task Name, Duration, Offset, ..., Crew, Manhours, ..., Progress)
    ws_sched.append(
        ["WBS", "Task Name", "Duration", "Offset", "Start Date", "End Date",
         "Predecessors", "Crew", "Manhours", "Labor Cost", "Total Cost", "Progress"]
    )
    # Row 5: task A1 — top-level, offset 0, 3-day duration
    ws_sched.append(["A1", "Mobilization", 3, 0, None, None, None, "Crew A", 24, 0, 0, 0])
    # Row 6: task A1.1 — child, offset 0, 1-day duration
    ws_sched.append(["A1.1", "Setup", 1, 0, None, None, None, "", 8, 0, 0, 0])

    xlsx_path = path / "smoke_test.xlsx"
    wb.save(str(xlsx_path))
    return xlsx_path


def test_round_trip(tmp_path):
    """Build a tiny Gantt workbook, run the converter, verify JSON output."""
    from estimating_tools.schedule.gantt_to_ganttwarrior import convert

    xlsx_path = _build_minimal_workbook(tmp_path)
    out_dir = tmp_path / "output"
    out_path = convert(xlsx_path, out_dir)

    assert out_path.exists(), "output .gw.json was not created"

    data = json.loads(out_path.read_text())

    # Top-level project fields
    assert data["name"]
    assert data["start_date"] == date(2026, 1, 5).isoformat()

    # Task count
    tasks = data["tasks"]
    assert len(tasks) == 2, f"Expected 2 tasks, got {len(tasks)}"

    # Verify WBS values and names are preserved
    wbs_map = {t["wbs"]: t for t in tasks}
    assert "A1" in wbs_map
    assert "A1.1" in wbs_map
    assert wbs_map["A1"]["name"] == "Mobilization"
    assert wbs_map["A1.1"]["name"] == "Setup"

    # Duration sanity: 3 work days → end date should be 2026-01-07 (Mon-Wed)
    assert wbs_map["A1"]["duration_days"] == 3
    assert wbs_map["A1"]["start_date"] == "2026-01-05"
    assert wbs_map["A1"]["end_date"] == "2026-01-07"

    # Child inherits parent's start (offset=0) → also 2026-01-05
    assert wbs_map["A1.1"]["start_date"] == "2026-01-05"
