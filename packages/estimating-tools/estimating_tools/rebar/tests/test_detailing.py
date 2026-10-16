"""ACI bend diameters and standard hook extensions (estimating aid, not design)."""
import pytest

from estimating_tools.rebar.detailing import (
    HOOKS, bend_diameter_in, hook_allowance_in, hook_extension_in,
)
from estimating_tools.rebar.model import BarSize


def test_bend_diameters_aci_25_3_1():
    assert bend_diameter_in(BarSize(5)) == pytest.approx(6 * 0.625)    # 6db for #3-#8
    assert bend_diameter_in(BarSize(9)) == pytest.approx(8 * 1.128)    # 8db for #9-#11
    assert bend_diameter_in(BarSize(14)) == pytest.approx(10 * 1.693)  # 10db for #14/#18


def test_hook_extensions_aci_25_3_1():
    db5 = 0.625
    assert hook_extension_in(BarSize(5), "90") == pytest.approx(12 * db5)
    # 180 hook: max(4db, 2.5in)
    assert hook_extension_in(BarSize(3), "180") == pytest.approx(2.5)
    assert hook_extension_in(BarSize(8), "180") == pytest.approx(4 * 1.0)


def test_stirrup_hooks_aci_25_3_2():
    assert hook_extension_in(BarSize(4), "stirrup90") == pytest.approx(6 * 0.5)
    assert hook_extension_in(BarSize(6), "stirrup90") == pytest.approx(12 * 0.75)
    # 135 stirrup: max(6db, 3in)
    assert hook_extension_in(BarSize(3), "stirrup135") == pytest.approx(3.0)
    assert hook_extension_in(BarSize(5), "stirrup135") == pytest.approx(6 * 0.625)


def test_unknown_hook_rejected():
    with pytest.raises(ValueError, match="unknown hook type"):
        hook_extension_in(BarSize(5), "45")


def test_stirrup_hooks_limited_to_small_bars():
    with pytest.raises(ValueError, match="stirrup hooks apply to #3"):
        hook_extension_in(BarSize(9), "stirrup90")


def test_hook_allowance_is_extension_plus_bend_arc():
    # allowance > extension (adds the bend arc length); monotone in size
    a5 = hook_allowance_in(BarSize(5), "90")
    assert a5 > hook_extension_in(BarSize(5), "90")
