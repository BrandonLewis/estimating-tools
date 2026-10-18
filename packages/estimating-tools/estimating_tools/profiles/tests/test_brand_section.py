"""The optional `brand:` profile section that Estimate Navigator's brand files come from."""
from __future__ import annotations

import warnings
from pathlib import Path

from estimating_tools.profiles.loader import load_one

BRAND = """\
kind: org
name: Example Paving
brand:
  short_name: Example Index
  logo: logo.svg
  icon_32: icons/32.png
  colors:
    light: { accent: "#B4531A" }
    dark:  { accent: "#F0A070" }
"""


def test_a_brand_section_loads_with_its_assets_resolved(tmp_path):
    (tmp_path / "profile.yaml").write_text(BRAND, encoding="utf-8")
    data = load_one(tmp_path)
    assert data["brand"]["short_name"] == "Example Index"
    assert Path(data["brand"]["logo"]) == (tmp_path / "logo.svg").resolve()
    assert Path(data["brand"]["icon_32"]) == (tmp_path / "icons" / "32.png").resolve()


def test_a_long_short_name_or_bad_colour_drops_the_section(tmp_path):
    (tmp_path / "profile.yaml").write_text(
        BRAND.replace("Example Index", "A name far too long for a ribbon"), encoding="utf-8")
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        assert "brand" not in load_one(tmp_path)
    (tmp_path / "profile.yaml").write_text(BRAND.replace("#B4531A", "orange"), encoding="utf-8")
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        assert "brand" not in load_one(tmp_path)
