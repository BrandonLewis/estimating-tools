"""Decision 5 on the profile route: a pack named by a configured org profile is
used, and a profile that is configured but fails to load (or loses its
`estimating.format` to field validation) is a format pack error, never a
silent fall back to the bundled pack."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import openpyxl
import pytest

from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.cli import main

ES = Path(fp.__file__).resolve().parent
DEMO_DIR = ES / "packs" / "demo"
SAMPLE = DEMO_DIR / "examples" / "demo-pipeline.estimate.yaml"


def _profile(tmp_path: Path, extra: str = "") -> Path:
    """A real profile directory whose estimating.format names a copied pack."""
    prof = tmp_path / "org"
    shutil.copytree(DEMO_DIR, prof / "packs" / "mine", ignore=shutil.ignore_patterns(
        "*.py", "__pycache__", "tests", "examples", "packs"))
    manifest = prof / "packs" / "mine" / "format.yaml"
    manifest.write_text(manifest.read_text().replace("name: demo", "name: mine"))
    (prof / "profile.yaml").write_text(
        "estimating:\n  format: packs/mine\n" + extra, encoding="utf-8")
    return prof


def _stamp(path: Path) -> str:
    wb = openpyxl.load_workbook(path)
    return {p.name: p.value for p in wb.custom_doc_props.props}["estimate_format"]


def _build(tmp_path: Path) -> tuple[int, Path]:
    out = tmp_path / "out.xlsx"
    return main(["build", str(SAMPLE), "-o", str(out)]), out


def test_a_valid_profile_names_the_pack_that_is_used(tmp_path, monkeypatch):
    monkeypatch.setenv("ESTIMATING_PROFILES", str(_profile(tmp_path)))
    rc, out = _build(tmp_path)
    assert rc == 0
    assert _stamp(out) == "mine 1"


def test_a_dropped_format_is_an_error_not_a_fall_back(tmp_path, monkeypatch, capsys):
    # An invalid sibling field makes field validation drop the whole
    # `estimating` section, format included.
    prof = _profile(tmp_path, "  waste_factors:\n    asphalt: 0.5\n")
    monkeypatch.setenv("ESTIMATING_PROFILES", str(prof))
    with pytest.warns(UserWarning):
        rc, out = _build(tmp_path)
    assert rc == 2 and not out.exists()
    err = capsys.readouterr().err
    assert "format pack error" in err and str(prof) in err


def test_a_profile_with_a_yaml_error_is_an_error(tmp_path, monkeypatch, capsys):
    prof = _profile(tmp_path, "naming: [unclosed\n")
    monkeypatch.setenv("ESTIMATING_PROFILES", str(prof))
    rc, out = _build(tmp_path)
    assert rc == 2 and not out.exists()
    assert "format pack error" in capsys.readouterr().err


def test_a_broken_profile_blocks_every_pack_resolving_command(tmp_path, monkeypatch, capsys):
    prof = _profile(tmp_path, "naming: [unclosed\n")
    monkeypatch.setenv("ESTIMATING_PROFILES", str(prof))
    assert main(["summarize", str(SAMPLE)]) == 2
    assert "format pack error" in capsys.readouterr().err


def test_no_profiles_configured_uses_the_bundled_pack(tmp_path, monkeypatch):
    """No profile configured -> the bundled pack — proven generically by
    redirecting the bundled pack to the demo pack rather than depending on
    whichever pack format_pack.py bundles today."""
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    demo = fp.load_pack(DEMO_DIR)
    monkeypatch.setattr(fp, "bundled_pack", lambda: demo)
    rc, out = _build(tmp_path)
    assert rc == 0
    assert _stamp(out) == "demo 1"


def test_one_layers_dropped_format_is_not_masked_by_another(tmp_path, monkeypatch, capsys):
    broken = _profile(tmp_path / "a", "  waste_factors:\n    asphalt: 0.5\n")
    valid = _profile(tmp_path / "b")
    monkeypatch.setenv("ESTIMATING_PROFILES", os.pathsep.join([str(valid), str(broken)]))
    with pytest.warns(UserWarning):
        rc, _ = _build(tmp_path)
    assert rc == 2
    assert str(broken) in capsys.readouterr().err
