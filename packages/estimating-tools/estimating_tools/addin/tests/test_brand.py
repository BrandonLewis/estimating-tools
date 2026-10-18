"""est-addin brand: brand.json from an org profile."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from estimating_tools.addin import brand as AB
from estimating_tools.addin.cli import main
from estimating_tools.profiles.model import Profile


def _profile_dir(tmp_path, brand_yaml: str) -> str:
    d = tmp_path / "prof"
    (d / "icons").mkdir(parents=True)
    for n in AB.ICON_SIZES:
        (d / "icons" / f"{n}.png").write_bytes(b"\x89PNG fake")
    (d / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (d / "profile.yaml").write_text(brand_yaml, encoding="utf-8")
    return str(d)


FULL = """\
kind: org
name: Example Paving
letterhead: { logo: logo.svg }
brand:
  short_name: Example Index
  support_url: https://example.com/help
""" + "".join(f"  icon_{n}: icons/{n}.png\n" for n in AB.ICON_SIZES) + """\
  colors:
    light: { accent: "#B4531A" }
"""


def test_an_empty_profile_is_the_generic_brand(tmp_path):
    assert AB.brand_from_profile(Profile(data={}), tmp_path) == AB.GENERIC


def test_a_profile_brand_overrides_and_copies_its_assets(tmp_path):
    out = tmp_path / "out"
    assert main(["brand", "--profile", _profile_dir(tmp_path, FULL), "-o", str(out)]) == 0
    b = json.loads((out / "brand.json").read_text(encoding="utf-8"))
    assert b["name"] == "Example Paving" and b["short_name"] == "Example Index"
    assert b["support_url"] == "https://example.com/help"
    assert b["colors"]["light"]["accent"] == "#B4531A"
    assert b["colors"]["light"]["surface"] == AB.GENERIC["colors"]["light"]["surface"]
    assert b["logo"] == "assets/logo.svg" and (out / "assets" / "logo.svg").exists()
    assert all((out / b["icons"][str(n)]).exists() for n in AB.ICON_SIZES)


def test_a_branded_profile_without_icons_is_refused(tmp_path, capsys):
    yaml_text = "kind: org\nname: Example Paving\nbrand: { short_name: Example }\n"
    assert main(["brand", "--profile", _profile_dir(tmp_path, yaml_text), "-o", str(tmp_path / "o")]) == 1
    assert "icon_16" in capsys.readouterr().err


def test_a_long_name_needs_a_short_name(tmp_path):
    p = Profile(data={"name": "A Very Long Organization Name", "brand": {"colors": {}}})
    b = AB.render_names(p.section("brand"), p.data["name"])
    assert b["short_name"] == "A Very Long"


def test_workbook_brand_is_name_and_colours_only():
    p = Profile(data={"name": "Example Paving",
                      "brand": {"logo": "/x.svg", "colors": {"light": {"accent": "#B4531A"}}}})
    assert AB.workbook_brand(p) == {"name": "Example Paving",
                                    "colors": {"light": {"accent": "#B4531A"}}}
    assert AB.workbook_brand(Profile(data={"name": "x"})) is None


# -- I2: a brand: section is required for a branded build -------------------

def test_brand_from_profile_ignores_a_name_only_profile(tmp_path):
    """A profile with a name but no brand: section is still the generic brand:
    the name and the letterhead logo are only consulted once brand: exists."""
    p = Profile(data={"name": "Example Paving", "letterhead": {"logo": "/x.svg"}})
    assert AB.brand_from_profile(p, tmp_path) == AB.GENERIC


def test_cli_warns_and_writes_generic_for_a_name_only_profile(tmp_path, capsys):
    d = tmp_path / "prof"
    d.mkdir()
    (d / "profile.yaml").write_text("kind: org\nname: Example Paving\n", encoding="utf-8")
    out = tmp_path / "o"
    assert main(["brand", "--profile", str(d), "-o", str(out)]) == 0
    assert json.loads((out / "brand.json").read_text(encoding="utf-8")) == AB.GENERIC
    assert "warning: profile has no brand: section; wrote the generic brand" in capsys.readouterr().err


# -- I1: a bad brand: section fails the build, loudly ------------------------

def test_cli_refuses_an_invalid_brand_section(tmp_path, capsys):
    d = tmp_path / "prof"
    d.mkdir()
    (d / "profile.yaml").write_text(
        "kind: org\nname: Example Paving\nbrand: not-an-object\n", encoding="utf-8")
    assert main(["brand", "--profile", str(d), "-o", str(tmp_path / "o")]) == 1
    assert "error: the profile's brand: section is invalid:" in capsys.readouterr().err


def test_cli_refuses_invalid_yaml(tmp_path, capsys):
    d = tmp_path / "prof"
    d.mkdir()
    (d / "profile.yaml").write_text("kind: org\nname: [unclosed\n", encoding="utf-8")
    assert main(["brand", "--profile", str(d), "-o", str(tmp_path / "o")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and err.strip() != "error:"


# -- I4: icons must actually be PNGs -----------------------------------------

def test_a_non_png_icon_is_refused(tmp_path, capsys):
    d = Path(_profile_dir(tmp_path, FULL))
    (d / "icons" / "16.png").write_bytes(b"not a png")
    assert main(["brand", "--profile", str(d), "-o", str(tmp_path / "o")]) == 1
    assert "icon_16" in capsys.readouterr().err


# -- M6: render_names word-boundary truncation and blank handling -----------

def test_a_blank_brand_name_falls_back_to_the_profile_name():
    b = AB.render_names({"name": "   "}, "Example Paving")
    assert b["name"] == "Example Paving"


def test_a_blank_short_name_is_derived_not_kept_blank():
    b = AB.render_names({"name": "Example Paving", "short_name": "   "}, None)
    assert b["short_name"] == "Example Paving"
