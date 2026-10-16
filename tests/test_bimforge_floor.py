"""estimating_tools' bimforge requirement must carry a lower bound.

The plugin bundles a specific bimforge wheel, and bimforge is published to PyPI
from BrandonLewis/BIMForge on the same version line. A BARE `bimforge`
requirement would be satisfied by ANY registry version, older included; the
floor pins the minimum to what this repo's code expects. And the floor must be
<= the bimforge version this repo builds, or the bundled wheel would stop
satisfying it and every install would break.

Deliberately parses with `re` and no TOML library: this repo supports Python
3.10, where `tomllib` is absent, and a guard that skips on a supported version
is not a guard. Same reason `scripts/check_release_version.py` reads versions
with a regex.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ET = ROOT / "packages" / "estimating-tools" / "pyproject.toml"
BF = ROOT / "packages" / "bimforge" / "pyproject.toml"
BUNDLED = ROOT / "plugins" / "estimating-core" / "dist"


def _version(pyproject: Path) -> tuple[int, ...]:
    """The [project] version, as a comparable tuple."""
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(
        encoding="utf-8"), re.M)
    assert m, f"no version in {pyproject}"
    return tuple(int(x) for x in m.group(1).split("."))


def _bimforge_requirements() -> list[tuple[str, str]]:
    """Every requirement spec naming bimforge, as (where, spec).

    `where` is the pyproject key whose array the spec sits in -- `dependencies`
    or an extra's name -- so a failure says which one to fix.
    """
    found, key = [], "?"
    for line in ET.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Za-z0-9_.-]+)\s*=\s*\[", line)
        if m:
            key = m.group(1)
        for spec in re.findall(r'"([^"]+)"', line):
            # bimforge, bimforge[all], bimforge>=x -- but not bimforge-foo
            if re.match(r"^bimforge\s*($|[\[><=!~;])", spec):
                found.append((key, spec))
    return found


def _floor(spec: str) -> tuple[int, ...] | None:
    m = re.search(r"(?:>=|==|~=)\s*([0-9]+(?:\.[0-9]+)*)", spec)
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def test_bimforge_is_required_somewhere():
    assert _bimforge_requirements(), (
        "no requirement names bimforge — this guard has lost its subject")


def test_every_bimforge_requirement_has_a_floor():
    bare = [(k, s) for k, s in _bimforge_requirements() if _floor(s) is None]
    assert not bare, (
        f"bare bimforge requirement {bare}: any registry version, older ones "
        f"included, would satisfy it")


def _bimforge_we_ship() -> tuple[int, ...]:
    """The bimforge version this tree ships: the source package's in the
    monorepo, the bundled wheel's in the public export (which takes bimforge
    from PyPI and carries no source)."""
    if BF.exists():
        return _version(BF)
    wheels = sorted(BUNDLED.glob("bimforge-*.whl"))
    assert wheels, f"no packages/bimforge and no bundled bimforge wheel under {BUNDLED}"
    return tuple(int(x) for x in wheels[-1].name.split("-")[1].split("."))


def test_no_floor_is_above_the_version_we_build():
    built = _bimforge_we_ship()
    for key, spec in _bimforge_requirements():
        floor = _floor(spec)
        assert floor is not None and floor <= built, (
            f"{key} floors bimforge at {floor} but this repo builds {built}; "
            f"the bundled wheel would not satisfy it")
