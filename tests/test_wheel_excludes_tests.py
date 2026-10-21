"""The shipped estimating_tools and bimforge wheels carry no tests and no
client project data.

142 test modules across 24 packages shipped to every customer, because packaging
included `estimating_tools*` wholesale with no exclusions.

The sample-bridge fixture DATA never shipped: setuptools package discovery collects only
.py modules, so the fixture .yaml/.json stayed in the repo. The sample-bridge assertion
below is kept deliberately, as a cheap tripwire against a future packaging change
that would start pulling package data out of test directories.

The exclusion assertions run over the COMMITTED wheels: those are what
customers actually received, and the drift guard normally keeps them level
with source.

The format-data assertion does NOT, and the difference is load-bearing.
During a release freeze the committed wheels are deliberately stale, so
asserting today's format layout over them asserts nothing about what the next
release ships — which is exactly what went wrong here. This file required
`estimate_spec/units.yaml`, `tokens.yaml`, `recipes.yaml` and
`schema/estimate.schema.json`; three of those were deleted and the fourth
renamed to `schema/skeleton.schema.json`, and the test kept passing because
the frozen wheels still carried the old layout. A wheel built from source
ships none of the four. That assertion now builds a wheel from source into a
tmp dir, so it tracks what packaging would ship today.

Lives in the repo-root tests/ on purpose — CI's pytest paths are
`packages/... manifest tests`, so a test elsewhere would never run.
"""
from __future__ import annotations

import fnmatch
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "packages" / "estimating-tools"

#: estimating_tools ships from two dist dirs; bimforge from three (calc-bim too).
DIST_DIRS = (ROOT / "plugins" / "estimating-core" / "dist",
             ROOT / "plugins" / "calc-bim" / "dist",
             ROOT / "openworker" / "skills" / "_dist")
PACKAGES = ("estimating_tools", "bimforge")


def _committed_wheels() -> list[Path]:
    found: list[Path] = []
    for d in DIST_DIRS:
        for package in PACKAGES:
            found.extend(sorted(d.glob(f"{package}-*.whl")))
    assert found, f"no committed wheels under {DIST_DIRS}"
    return found


WHEELS = _committed_wheels()


@pytest.mark.parametrize("wheel", WHEELS, ids=lambda w: w.name)
def test_wheel_ships_no_tests(wheel):
    names = zipfile.ZipFile(wheel).namelist()
    offenders = [n for n in names
                 if "/tests/" in n or n.rstrip("/").endswith("/tests")]
    assert not offenders, (
        f"{wheel.name} ships {len(offenders)} test members, e.g. "
        f"{offenders[:5]} — exclude them in "
        "packages/estimating-tools/pyproject.toml, then re-run "
        "scripts/build_plugin_wheel.py and openworker/port_skills.py")


@pytest.mark.parametrize("wheel", WHEELS, ids=lambda w: w.name)
def test_wheel_ships_no_client_project_data(wheel):
    """The sample-bridge fixture carries real bid items. The de-org scan bans org
    branding, user paths and secrets, not project identifiers — so this is its
    own tripwire."""
    names = zipfile.ZipFile(wheel).namelist()
    offenders = [n for n in names if "sample_bridge" in n.lower()]
    assert not offenders, f"{wheel.name} ships client project data: {offenders}"


#: What the estimating_tools wheel must carry for `est-estimate` to work at
#: all on a fresh install: the bundled fieldbook pack (its manifest, the documents
#: it names, and its worked example) and the schema skeleton the pack's
#: vocabulary is composed into. A pack is data, so a missing file here is not
#: an import error at build time — it is a FormatPackError the first time a
#: customer runs the tool.
REQUIRED_FORMAT_DATA = (
    "estimating_tools/estimate_spec/packs/fieldbook/format.yaml",
    "estimating_tools/estimate_spec/packs/fieldbook/units.yaml",
    "estimating_tools/estimate_spec/packs/fieldbook/tokens.yaml",
    "estimating_tools/estimate_spec/packs/fieldbook/recipes.yaml",
    "estimating_tools/estimate_spec/packs/fieldbook/vocabulary.yaml",
    "estimating_tools/estimate_spec/packs/fieldbook/seed.yaml",
    "estimating_tools/estimate_spec/schema/skeleton.schema.json",
    # The pack-author contract: the required key set a third party needs to
    # write a pack. It is only documentation if it reaches them.
    "estimating_tools/estimate_spec/packs/README.md",
)

#: The bundled pack's examples are what the skills point a new user at.
REQUIRED_FORMAT_GLOB = "estimating_tools/estimate_spec/packs/fieldbook/examples/*.estimate.yaml"


@pytest.fixture(scope="module")
def freshly_built_wheel(tmp_path_factory):
    """An estimating_tools wheel built from the CURRENT source tree.

    Not the committed one: during a release freeze that is stale by design,
    and a format-layout assertion over a stale wheel proves nothing about the
    next release. Nothing is written under any dist/.
    """
    pytest.importorskip("build", reason="`python -m build` is not available here")
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_plugin_wheel import build_wheel

    return build_wheel(tmp_path_factory.mktemp("wheel"), PACKAGE_DIR)


def test_wheel_still_ships_the_format_data_files(freshly_built_wheel):
    """The test exclusion must not take the bundled pack or the skeleton with it."""
    names = set(zipfile.ZipFile(freshly_built_wheel).namelist())
    missing = [r for r in REQUIRED_FORMAT_DATA if r not in names]
    assert not missing, (
        f"{freshly_built_wheel.name} does not ship {missing} — fix the "
        "[tool.setuptools.package-data] globs in "
        "packages/estimating-tools/pyproject.toml")
    assert any(fnmatch.fnmatch(n, REQUIRED_FORMAT_GLOB) for n in names), \
        f"{freshly_built_wheel.name} ships no {REQUIRED_FORMAT_GLOB}"
    package = PACKAGE_DIR / "estimating_tools"
    examples = package / "estimate_spec" / "packs" / "fieldbook" / "examples"
    missing_examples = [p.relative_to(PACKAGE_DIR).as_posix()
                        for p in examples.rglob("*")
                        if p.suffix in (".yaml", ".json")
                        and p.relative_to(PACKAGE_DIR).as_posix() not in names]
    assert not missing_examples, f"wheel lacks example assets: {missing_examples}"


def test_the_fresh_wheel_ships_the_manifest_template(freshly_built_wheel):
    """estimating_tools.addin.manifest reads manifest.xml.tmpl via
    importlib.resources at runtime; the [tool.setuptools.package-data] entry
    for "estimating_tools.addin" must keep shipping it."""
    names = set(zipfile.ZipFile(freshly_built_wheel).namelist())
    assert "estimating_tools/addin/manifest.xml.tmpl" in names, (
        f"{freshly_built_wheel.name} does not ship the manifest template — fix the "
        "[tool.setuptools.package-data] globs in "
        "packages/estimating-tools/pyproject.toml")


def test_the_fresh_wheel_ships_generic_brand_assets(freshly_built_wheel):
    brand = json.loads((ROOT / "excel-addin/brand/brand.json").read_text())
    with zipfile.ZipFile(freshly_built_wheel) as wheel:
        for relative in (brand["logo"], *brand["icons"].values()):
            member = f"estimating_tools/addin/{relative}"
            assert member in wheel.namelist(), f"generic brand is missing {relative}"
            assert wheel.read(member) == (ROOT / "excel-addin/brand" / relative).read_bytes()


def test_the_deleted_format_layout_is_not_resurrected(freshly_built_wheel):
    """units/tokens/recipes at the estimate_spec root, and estimate.schema.json,
    were the pre-pack layout. Their absence is the point of the extraction; a
    build that puts them back means a pack leaked into the engine again."""
    names = set(zipfile.ZipFile(freshly_built_wheel).namelist())
    gone = [n for n in (
        "estimating_tools/estimate_spec/units.yaml",
        "estimating_tools/estimate_spec/tokens.yaml",
        "estimating_tools/estimate_spec/recipes.yaml",
        "estimating_tools/estimate_spec/schema/estimate.schema.json",
    ) if n in names]
    assert not gone, f"{freshly_built_wheel.name} resurrects the pre-pack layout: {gone}"


def ships_retired_demo_pack(names) -> list:
    """Wheel paths under the retired estimate_spec/packs/demo/ (fieldbook phase 3b)."""
    return sorted(n for n in names if n.startswith("estimating_tools/estimate_spec/packs/demo/"))


def test_the_retired_demo_pack_is_not_shipped(freshly_built_wheel):
    """packs/demo was retired when fieldbook became the bundled default; its
    frozen copy is the test-only legacy_demo fixture. A build that ships it
    again would put a second, stale default pack in users' hands."""
    names = zipfile.ZipFile(freshly_built_wheel).namelist()
    assert not ships_retired_demo_pack(names), (
        f"{freshly_built_wheel.name} ships the retired demo pack: "
        f"{ships_retired_demo_pack(names)}")


@pytest.mark.parametrize("wheel", WHEELS, ids=lambda w: w.name)
def test_bimforge_wheel_still_ships_its_package_data(wheel):
    """bimforge ships templates/examples as package-data; the test exclusion
    must not remove them."""
    if not wheel.name.startswith("bimforge-"):
        pytest.skip("bimforge-only assertion")
    names = set(zipfile.ZipFile(wheel).namelist())
    assert any(n.startswith("bimforge/cad/templates/") for n in names), \
        f"bimforge/cad/templates/* missing from {wheel.name}"
    assert any(n.startswith("bimforge/bim/plansheet/") and n.endswith(".yaml")
               for n in names), \
        f"bimforge/bim/plansheet/*.yaml missing from {wheel.name}"
