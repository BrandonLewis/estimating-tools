"""Tests for the earthwork pure-math module.

Ported truths:
- bridge-pilot ``build_exback_takeoff.py`` benched-excavation
  formulas (neat prism, one-face wedge, all-round bench increment).
- canal-job "9 - Canal Earthwork, Borrow Pits, and Clearing and Grubbing"
  sheet CS26 (revised Addendum No. 2) mass-haul worked example.
"""
from __future__ import annotations

import math

import pytest

from estimating_tools.takeoff import earthwork


# ------------------------------------------------------------------ prisms
def test_prism_cy():
    # 10 x 10 x 9 ft = 900 CF = 900/27 CY
    assert earthwork.prism_cy(10, 10, 9) == pytest.approx(900 / 27)


def test_wedge_cy():
    # One-face lay-back: length * run * depth / 2, in CY
    assert earthwork.wedge_cy(length_ft=10, depth_ft=9, run_ft=3) == pytest.approx(
        10 * 3 * 9 / 2 / 27
    )


def test_bench_increment_cy_exact():
    # A0 = 10*10 = 100; A1 = (10+2*3)*(10+2*3) = 256
    # pit = depth/3 * (A0 + A1 + sqrt(A0*A1)) = 9/3 * (100+256+160) = 1548 CF
    # increment = (1548 - 900) / 27 = 24.0 CY exactly
    a0 = 10 * 10
    a1 = (10 + 2 * 3) * (10 + 2 * 3)
    pit_cf = 9 / 3 * (a0 + a1 + math.sqrt(a0 * a1))
    assert pit_cf == 1548.0
    assert earthwork.bench_increment_cy(10, 10, 9, 3) == 24.0


def test_bench_increment_docstring_carries_the_double_count_lesson():
    # bridge-pilot: returning the raw pit double-counts the pay volume — "Bent 2 came
    # out 640 CY against a real dig of 372." The lesson must not be dropped.
    doc = earthwork.bench_increment_cy.__doc__
    assert doc is not None
    assert "640" in doc
    assert "372" in doc


# ------------------------------------------------------- consolidation math
def test_fill_required_cy_mcmullin_total():
    # canal-job CS26: 537,200 CY neat fill at 25% consolidation ->
    # 537,200 / (1 - 0.25) = 716,266.7 CY required borrow (published 716,200).
    assert earthwork.fill_required_cy(537_200, 0.25) == pytest.approx(
        716_266.7, rel=1e-4
    )


def test_fill_required_cy_rejects_percent_style_factor():
    with pytest.raises(ValueError, match="0.25"):
        earthwork.fill_required_cy(537_200, 25)


def test_fill_required_cy_rejects_negative_factor():
    with pytest.raises(ValueError):
        earthwork.fill_required_cy(537_200, -0.1)


# ------------------------------------------------------------- mass haul
# canal-job sheet CS26 Earthwork Summary (revised by Addendum No. 2),
# reach totals as published (cut/fill in CY):
#   Reach 1: fill  38,900 / cut 149,900  (net +111,000)
#   Reach 2: fill 270,000 / cut 204,900  (net  -65,100)
#   Reach 3: fill 154,800 / cut 170,300  (net  +15,500)
#   Reach 4: fill  73,500 / cut 115,500  (net  +42,000)
# Totals: cut 640,600 / fill 537,200; 25% consolidation -> 716,200 CY
# required borrow -> 75,600 CY NET IMPORT (raw numbers say 103,400 net export).
MCMULLIN_REACHES = [
    {"name": "Reach 1", "cut_cy": 149_900, "fill_cy": 38_900},
    {"name": "Reach 2", "cut_cy": 204_900, "fill_cy": 270_000},
    {"name": "Reach 3", "cut_cy": 170_300, "fill_cy": 154_800},
    {"name": "Reach 4", "cut_cy": 115_500, "fill_cy": 73_500},
]


def test_mass_haul_mcmullin():
    result = earthwork.mass_haul(MCMULLIN_REACHES, consolidation=0.25)

    totals = result["totals"]
    # Raw volumes: 640,600 cut vs 537,200 fill = 103,400 CY net EXPORT
    assert totals["cut_cy"] == pytest.approx(640_600)
    assert totals["fill_cy"] == pytest.approx(537_200)
    assert totals["raw_net_cy"] == pytest.approx(103_400)
    # 25% consolidation flips it: 75,600 CY net IMPORT (positive = must import)
    assert totals["net_import_cy"] == pytest.approx(75_600, abs=100)

    reaches = result["reaches"]
    assert len(reaches) == 4
    # Reach 2 is the fill-hungry reach: -65,100 CY raw net
    reach2 = reaches[1]
    assert reach2["name"] == "Reach 2"
    assert reach2["raw_net_cy"] == pytest.approx(-65_100)
    # Every reach row carries the per-reach dict fields
    for reach in reaches:
        for key in ("name", "cut_cy", "fill_cy", "raw_net_cy",
                    "fill_required_cy", "net_import_cy"):
            assert key in reach
