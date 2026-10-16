"""Tests for the rebar data model."""
from __future__ import annotations

import pytest

from estimating_tools.rebar import BAR_SIZES, BarSize, Rebar


def test_bar_sizes_integrity():
    """The ASTM A615 table carries all 11 imperial sizes, ordered sanely."""
    assert len(BAR_SIZES) == 11
    assert sorted(BAR_SIZES) == [3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 18]
    ordered = [BAR_SIZES[n] for n in sorted(BAR_SIZES)]
    diameters = [t[0] for t in ordered]
    areas = [t[1] for t in ordered]
    weights = [t[2] for t in ordered]
    assert diameters == sorted(diameters)
    assert areas == sorted(areas)
    assert weights == sorted(weights), "weights must increase with bar size"
    for d, a, w in ordered:
        assert d > 0 and a > 0 and w > 0


def test_bar_size_properties():
    b5 = BarSize(5)
    assert b5.diameter_in == 0.625
    assert b5.area_in2 == 0.31
    assert b5.weight_lb_per_ft == 1.043
    assert str(b5) == "#5"


def test_unknown_bar_size_is_a_clear_value_error():
    with pytest.raises(ValueError, match=r"unknown bar size #12.*A615"):
        BarSize(12)  # no #12 in ASTM A615 (sizes jump 11 -> 14)


def test_total_weight_lb_sanity():
    # 10 x #4 bars at 20 ft: 0.668 lb/ft * 20 ft * 10 = 133.6 lb
    bar = Rebar(size=BarSize(4), length_ft=20.0, count=10, mark="A1", spacing_in=12.0)
    assert bar.total_weight_lb == pytest.approx(133.6)
    # default count is a single bar
    assert Rebar(size=BarSize(18), length_ft=1.0).total_weight_lb == pytest.approx(13.6)
