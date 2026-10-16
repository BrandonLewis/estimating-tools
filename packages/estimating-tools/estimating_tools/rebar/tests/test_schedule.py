"""Tests for the bar bending schedule (BBS): cut-length/weight math, table
renderers, LBS takeoff rows, and the xlsx writer."""
from __future__ import annotations

import pytest

from estimating_tools.rebar.detailing import hook_allowance_in
from estimating_tools.rebar.model import BarSize
from estimating_tools.rebar.schedule import BarMark, BarSchedule, DEFAULT_WASTE_FACTOR
from estimating_tools.takeoff.core import WASTE_FACTORS
from estimating_tools.takeoff.model import TakeoffRow


def _mark_a1() -> BarMark:
    # #5 x 20 bars, legs 96 in + 24 in, one 90-degree hook.
    return BarMark(mark="A1", size=BarSize(5), count=20, legs_in=[96.0, 24.0], hooks=["90"])


# --- BarMark: cut-length / weight math -------------------------------------

def test_hand_computed_cut_length_and_weight():
    mark = _mark_a1()
    size = BarSize(5)

    expected_hook_allowance = hook_allowance_in(size, "90")
    expected_cut_in = 96.0 + 24.0 + expected_hook_allowance
    expected_cut_ft = expected_cut_in / 12.0
    expected_weight_lb = expected_cut_ft * size.weight_lb_per_ft * 20

    assert mark.cut_length_in == pytest.approx(expected_cut_in)
    assert mark.cut_length_ft == pytest.approx(expected_cut_ft)
    assert mark.weight_lb == pytest.approx(expected_weight_lb)

    # Recomputed reference values (see task report): allowance ~10.9361 in,
    # cut ~130.9361 in / 10.9113 ft, weight ~227.61 lb.
    assert mark.cut_length_in == pytest.approx(130.9361, rel=1e-4)
    assert mark.cut_length_ft == pytest.approx(10.9113, rel=1e-4)
    assert mark.weight_lb == pytest.approx(227.61, rel=1e-3)


def test_cut_length_with_no_hooks_is_just_the_legs():
    mark = BarMark(mark="B1", size=BarSize(4), count=5, legs_in=[36.0, 12.0, 12.0])
    assert mark.cut_length_in == pytest.approx(60.0)
    assert mark.cut_length_ft == pytest.approx(5.0)
    assert mark.weight_lb == pytest.approx(5.0 * BarSize(4).weight_lb_per_ft * 5)


def test_cut_length_sums_multiple_hooks():
    size = BarSize(4)
    mark = BarMark(mark="C1", size=size, count=1, legs_in=[24.0], hooks=["90", "90"])
    expected = 24.0 + 2 * hook_allowance_in(size, "90")
    assert mark.cut_length_in == pytest.approx(expected)


# --- BarMark validation ------------------------------------------------------

def test_count_must_be_at_least_one():
    with pytest.raises(ValueError, match="count must be >= 1"):
        BarMark(mark="A1", size=BarSize(5), count=0, legs_in=[24.0])


def test_legs_must_not_be_empty():
    with pytest.raises(ValueError, match="legs_in must not be empty"):
        BarMark(mark="A1", size=BarSize(5), count=1, legs_in=[])


def test_leg_lengths_must_be_positive():
    with pytest.raises(ValueError, match="leg lengths must be positive"):
        BarMark(mark="A1", size=BarSize(5), count=1, legs_in=[24.0, 0.0])

    with pytest.raises(ValueError, match="leg lengths must be positive"):
        BarMark(mark="A1", size=BarSize(5), count=1, legs_in=[-12.0])


# --- BarSchedule: totals -----------------------------------------------------

def test_schedule_total_weight_and_weight_by_size():
    a1 = _mark_a1()
    b1 = BarMark(mark="B1", size=BarSize(4), count=5, legs_in=[36.0, 12.0, 12.0])
    sched = BarSchedule(title="Footing F1", marks=[a1, b1])

    assert sched.total_weight_lb == pytest.approx(a1.weight_lb + b1.weight_lb)

    by_size = sched.weight_by_size()
    assert by_size == {
        5: pytest.approx(a1.weight_lb),
        4: pytest.approx(b1.weight_lb),
    }


def test_duplicate_marks_are_rejected():
    a1 = _mark_a1()
    a1_dup = BarMark(mark="A1", size=BarSize(4), count=1, legs_in=[10.0])
    with pytest.raises(ValueError, match="duplicate mark 'A1'"):
        BarSchedule(title="Footing F1", marks=[a1, a1_dup])


# --- to_rows / to_markdown ---------------------------------------------------

def test_to_rows_shape_and_values():
    a1 = _mark_a1()
    sched = BarSchedule(title="Footing F1", marks=[a1])
    rows = sched.to_rows()

    assert len(rows) == 1
    row = rows[0]
    assert row["mark"] == "A1"
    assert row["size"] == "#5"
    assert row["count"] == 20
    assert row["legs"] == "96 + 24"
    assert row["hooks"] == "90"
    assert row["cut_ft"] == pytest.approx(round(a1.cut_length_ft, 2))
    assert row["weight_lb"] == pytest.approx(round(a1.weight_lb, 1))


def test_to_markdown_contains_header_mark_row_and_total():
    a1 = _mark_a1()
    sched = BarSchedule(title="Footing F1", marks=[a1])
    md = sched.to_markdown()

    assert "# Footing F1" in md
    assert "| Mark | Size | Count | Legs (in) | Hooks | Cut (ft) | Weight (lb) |" in md
    assert "|---|---|---|---|---|---|---|" in md
    assert "| A1 | #5 | 20 |" in md
    assert f"{sched.total_weight_lb:.1f}" in md
    assert "**Total**" in md


# --- to_takeoff_rows ---------------------------------------------------------

def test_takeoff_rows_construct_a_takeoff_row_with_lbs_and_waste():
    a1 = _mark_a1()
    sched = BarSchedule(title="Footing F1", marks=[a1])

    rows = sched.to_takeoff_rows(cost_code="03-2100", item_number="12", schedule="F1")
    assert len(rows) == 1
    row = rows[0]

    takeoff_row = TakeoffRow(**row)  # must construct cleanly
    assert takeoff_row.kind == "quantity"
    assert takeoff_row.unit == "LBS"
    assert takeoff_row.description == "Footing F1"
    assert takeoff_row.cost_code == "03-2100"
    assert takeoff_row.item_number == "12"
    assert takeoff_row.schedule == "F1"
    assert takeoff_row.waste_factor == pytest.approx(DEFAULT_WASTE_FACTOR)
    assert DEFAULT_WASTE_FACTOR == WASTE_FACTORS["rebar"]
    assert takeoff_row.quantity == pytest.approx(
        round(sched.total_weight_lb * DEFAULT_WASTE_FACTOR, 1)
    )
    assert "A1" in takeoff_row.notes


def test_takeoff_rows_honor_a_custom_waste_factor():
    a1 = _mark_a1()
    sched = BarSchedule(title="Footing F1", marks=[a1])
    rows = sched.to_takeoff_rows(waste_factor=1.10)
    takeoff_row = TakeoffRow(**rows[0])
    assert takeoff_row.waste_factor == pytest.approx(1.10)
    assert takeoff_row.quantity == pytest.approx(round(sched.total_weight_lb * 1.10, 1))


# --- to_xlsx -----------------------------------------------------------------

def test_to_xlsx_round_trip(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    a1 = _mark_a1()
    b1 = BarMark(mark="B1", size=BarSize(4), count=5, legs_in=[36.0, 12.0, 12.0])
    sched = BarSchedule(title="Footing F1", marks=[a1, b1])

    out = tmp_path / "bbs.xlsx"
    sched.to_xlsx(out)
    assert out.exists()

    wb = openpyxl.load_workbook(out)
    ws = wb.active

    assert ws.cell(1, 1).value == "Footing F1"
    header = [ws.cell(3, c).value for c in range(1, 8)]
    assert header == ["Mark", "Size", "Count", "Legs (in)", "Hooks", "Cut (ft)", "Weight (lb)"]

    assert ws.cell(4, 1).value == "A1"
    assert ws.cell(4, 2).value == "#5"
    assert ws.cell(4, 3).value == 20
    assert ws.cell(4, 7).value == pytest.approx(round(a1.weight_lb, 1))

    assert ws.cell(5, 1).value == "B1"

    total_row = ws.cell(6, 1).value
    assert total_row == "Total"
    assert ws.cell(6, 7).value == pytest.approx(round(sched.total_weight_lb, 1))


def test_to_xlsx_missing_openpyxl_gives_clean_error(monkeypatch, tmp_path):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("no module named openpyxl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    sched = BarSchedule(title="Footing F1", marks=[_mark_a1()])
    with pytest.raises(ImportError, match=r"pip install 'estimating_tools\[excel\]'"):
        sched.to_xlsx(tmp_path / "bbs.xlsx")


def test_invalid_hook_rejected_at_construction():
    with pytest.raises(ValueError, match="mark 'S1'.*stirrup hooks apply to #3"):
        BarMark(mark="S1", size=BarSize(9), count=2, legs_in=[24.0],
                hooks=["stirrup90"])


def test_unknown_hook_rejected_at_construction():
    with pytest.raises(ValueError, match="mark 'X1'.*unknown hook type"):
        BarMark(mark="X1", size=BarSize(5), count=1, legs_in=[24.0],
                hooks=["45"])
