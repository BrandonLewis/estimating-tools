"""Structural boundary: shipped package data carries no per-org content at all.

``scripts/deorg_scan.py`` is a keyword scan -- it matches a fixed list of
banned words. It cannot catch a client-derived numbering scheme, trade list,
rate table, or a 117-entry cost-code library that happens to contain none of
those words -- which is exactly how client data has ended up committed
elsewhere in this estate (see docs/superpowers/plans/2026-08-15-three-bucket-
survey.md's dir-map, fixed under Plan C Task 10). These tests check STRUCTURE
instead of vocabulary:

* no stray format-pack YAML sits at the engine root -- format data belongs
  only under ``packs/<name>/`` (shipped, generic) or in a consumer's own
  external profile (never in this repo at all);
* every SHIPPED pack (``ES/packs/*``) declares ``provenance: authored`` --
  the assertion is scoped to what ``pyproject.toml`` actually ships
  (``packs/*/*.yaml``), not to every pack the engine can load, because a
  consumer's own pack lives outside this repo and was never authored by us;
* ``provenance`` stays optional at the loader level, so a consumer pack that
  does not declare it is not an error -- only a *shipped* pack without one is
  a test failure here.
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from estimating_tools.estimate_spec import format_pack as fp

ES_DIR = fp.ENGINE_DIR


def test_engine_ships_no_pack_yaml_outside_packs():
    """Format data lives in packs/ or in a consumer's profile. Never at ES/ root."""
    stray = [p for p in ES_DIR.glob("*.yaml")]
    assert stray == [], f"pack data at engine root: {stray}"


def test_the_root_yaml_check_has_teeth(tmp_path):
    """Prove the check above is a real gate, not a vacuous pass because the
    engine root just happens to be clean today.

    Exercised against a throwaway copy of the engine tree -- a stray
    ``format.yaml`` is dropped back at the (copied) root the way it used to
    sit before Plan C Task 8 moved the reference pack out -- never by
    committing such a file to this repo."""
    shadow = tmp_path / "estimate_spec"
    shutil.copytree(ES_DIR, shadow, ignore=shutil.ignore_patterns("__pycache__"))
    assert list(shadow.glob("*.yaml")) == []  # sanity: the copy starts clean too

    (shadow / "format.yaml").write_text("name: stray\nversion: 1\n", encoding="utf-8")

    stray = list(shadow.glob("*.yaml"))
    assert stray == [shadow / "format.yaml"], (
        "a format.yaml dropped at the engine root must be detected by the same "
        "glob the real test above runs -- if this fails, the structural check "
        "itself is broken, not just the tree it's checking"
    )


def test_shipped_packs_are_authored_generic():
    """Every shipped pack declares provenance: authored.

    Scoped to ``ES/packs/*`` -- what pyproject.toml's package-data actually
    ships (``packs/*/*.yaml``) -- not to ``tests/fixtures/packs/*``, which is
    developer/test material excluded from the wheel build."""
    shipped = list((ES_DIR / "packs").glob("*/format.yaml"))
    assert shipped, "expected at least one shipped pack under ES/packs/"
    for fmt in shipped:
        doc = yaml.safe_load(fmt.read_text(encoding="utf-8"))
        assert doc.get("provenance") == "authored", fmt


def test_provenance_is_optional_for_a_consumer_pack(tmp_path):
    """load_pack must not require provenance: a consumer's own pack (authored
    outside this repo, never by us) is not forced to claim it. Only a
    *shipped* pack without one is a test failure (the test above) -- the
    loader itself stays permissive."""
    shadow = tmp_path / "no_provenance_pack"
    shutil.copytree(ES_DIR / "packs" / "fieldbook", shadow, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = shadow / "format.yaml"
    doc = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    doc.pop("provenance", None)
    manifest.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    pack = fp.load_pack(shadow)  # must not raise -- provenance is optional
    assert pack.name == "fieldbook"


def test_load_pack_accepts_provenance_authored():
    """The manifest loader accepts the provenance key on a real shipped pack
    (it doesn't reject unknown top-level manifest keys) -- allowing
    provenance: is not a behavior change to load_pack, just documented here
    so a future stricter manifest schema doesn't silently start rejecting it."""
    pack = fp.load_pack(ES_DIR / "packs" / "fieldbook")
    assert pack.name == "fieldbook"
