"""Simplified ACI 318-19 development/lap lengths (estimating aid)."""
import pytest

from estimating_tools.rebar.develop import development_length_in, lap_length_in
from estimating_tools.rebar.model import BarSize


def test_development_small_bar_grade60_4000psi():
    # #5, fc'=4000, fy=60000, bottom, uncoated:
    # ld = (60000*1.0*1.0 / (25*1.0*sqrt(4000))) * 0.625 = 23.717...
    assert development_length_in(BarSize(5), fc_psi=4000) == pytest.approx(23.72, abs=0.01)


def test_development_large_bar_uses_20_denominator():
    # #8 -> (60000 / (20*sqrt(4000))) * 1.0 = 47.43...
    assert development_length_in(BarSize(8), fc_psi=4000) == pytest.approx(47.43, abs=0.01)


def test_top_bar_and_epoxy_factors():
    base = development_length_in(BarSize(5), fc_psi=4000)
    assert development_length_in(BarSize(5), fc_psi=4000, top_bar=True) == pytest.approx(1.3 * base)
    assert development_length_in(BarSize(5), fc_psi=4000, epoxy=True) == pytest.approx(1.5 * base)
    # psi_t * psi_e need not exceed 1.7
    combo = development_length_in(BarSize(5), fc_psi=4000, top_bar=True, epoxy=True)
    assert combo == pytest.approx(1.7 * base)


def test_minimum_12in():
    assert development_length_in(BarSize(3), fc_psi=10000) >= 12.0


def test_sqrt_fc_capped_at_100():
    # sqrt(fc') taken as <= 100 psi (fc' > 10000 gives no further credit)
    assert development_length_in(BarSize(5), fc_psi=16000) == pytest.approx(
        development_length_in(BarSize(5), fc_psi=10000))


def test_lap_classes():
    ld = development_length_in(BarSize(5), fc_psi=4000)
    assert lap_length_in(BarSize(5), fc_psi=4000) == pytest.approx(1.3 * ld)       # Class B default
    assert lap_length_in(BarSize(5), fc_psi=4000, splice_class="A") == pytest.approx(max(ld, 12.0))
    with pytest.raises(ValueError, match="splice class"):
        lap_length_in(BarSize(5), fc_psi=4000, splice_class="C")


def test_bad_inputs():
    with pytest.raises(ValueError, match="fc_psi"):
        development_length_in(BarSize(5), fc_psi=0)


def test_lightweight_lengthens_development():
    # lambda divides: lightweight concrete lengthens development length
    base = development_length_in(BarSize(5), fc_psi=4000)
    assert development_length_in(BarSize(5), fc_psi=4000, lightweight=True) == pytest.approx(base / 0.75)


def test_grade_factor_psi_g():
    base = development_length_in(BarSize(5), fc_psi=4000)
    # Grade 80: linear fy scaling x psi_g 1.15 (Table 25.4.2.5)
    g80 = development_length_in(BarSize(5), fc_psi=4000, fy_psi=80000)
    assert g80 == pytest.approx(base * (80000 / 60000) * 1.15)
    g100 = development_length_in(BarSize(5), fc_psi=4000, fy_psi=100000)
    assert g100 == pytest.approx(base * (100000 / 60000) * 1.3)
