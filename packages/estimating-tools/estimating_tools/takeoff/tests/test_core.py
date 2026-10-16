import math

import pytest

from estimating_tools.takeoff import core


def test_area_takeoff_sf_with_concrete_waste():
    r = core.calculate_takeoff("slab", {"length": 10, "width": 10}, "SF", "concrete")
    assert r["base_quantity"] == 100.0
    assert r["waste_factor"] == 1.05
    assert r["quantity_with_waste"] == 105.0


def test_volume_takeoff_cy_uses_depth():
    r = core.calculate_takeoff("footing", {"length": 27, "width": 1, "depth": 1}, "CY")
    assert r["base_quantity"] == 1.0  # 27 CF / 27


def test_convert_sf_to_sy():
    r = core.convert_units(9, "SF", "SY")
    assert r["converted_quantity"] == 1.0
    assert math.isclose(r["conversion_factor"], 1 / 9)


def test_convert_ton_to_cy_asphalt():
    r = core.convert_units(2.4, "TON", "CY", "asphalt")
    assert math.isclose(r["converted_quantity"], 1.0)
    assert r["material_type"] == "asphalt"


def test_unsupported_unit_raises():
    with pytest.raises(ValueError):
        core.calculate_takeoff("mystery", {"length": 1}, "MGAL")


def test_undefined_conversion_raises():
    with pytest.raises(ValueError):
        core.convert_units(100, "LF", "CY")


def test_dbe_goal_amount_and_generic_requirements():
    r = core.check_dbe_requirements("P-1", 1_000_000, 10)
    assert r["dbe_goal_amount"] == 100000.0
    assert all("Caltrans" not in item for item in r["requirements"])


def test_asphalt_waste_factor_is_3_percent():
    # R1 item 1: the estimator-agent example applied concrete's 1.05 to
    # asphalt; 1.03 is the agnostic default both code and skill table state.
    assert core.WASTE_FACTORS["asphalt"] == 1.03


def test_profile_waste_factor_overrides_builtin():
    r = core.calculate_takeoff(
        "footing concrete", {"length": 10, "width": 10, "depth": 2.7}, "CY",
        material_type="footing_concrete",
        waste_factors={"footing_concrete": 1.15})
    assert r["waste_factor"] == 1.15
    assert r["waste_source"] == "profile"


def test_builtin_fallback_reports_default_source():
    r = core.calculate_takeoff("paving", {"length": 9, "width": 1}, "SF",
                               material_type="asphalt", waste_factors={})
    assert r["waste_factor"] == 1.03
    assert r["waste_source"] == "default"


def test_profile_default_key_beats_builtin_default():
    r = core.calculate_takeoff("misc", {"length": 1, "width": 1}, "SF",
                               material_type="unknown_material",
                               waste_factors={"default": 1.07})
    assert r["waste_factor"] == 1.07
    assert r["waste_source"] == "profile"


def test_profile_waste_factors_survives_missing_profiles_deps(monkeypatch):
    # Base installs lack jsonschema; profile lookup must degrade to {} not crash.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("estimating_tools.profiles.loader"):
            raise ImportError("No module named 'jsonschema'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert core.profile_waste_factors() == {}


def test_profile_waste_factors_loads_from_profile_dir(tmp_path):
    (tmp_path / "profile.yaml").write_text(
        "estimating:\n  waste_factors:\n    wall_concrete: 1.10\n",
        encoding="utf-8")
    from estimating_tools.profiles.loader import load
    prof = load([tmp_path])
    assert core.profile_waste_factors(prof) == {"wall_concrete": 1.10}
