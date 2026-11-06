"""estimating_tools' bimforge requirement must carry a lower bound.

bimforge is developed and released in BrandonLewis/BIMForge; this repo takes
it from PyPI. A BARE `bimforge` requirement would be satisfied by ANY registry
version, older included; the floor pins the minimum to what this repo's code
expects. The plugins bundle exactly the floored release
(`scripts/build_plugin_wheel.py --pypi bimforge`), so the bundled wheel must
be that version: lower and it would not satisfy the floor, higher and the
floor no longer says what the plugins ship.

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
BUNDLED = ROOT / "plugins" / "estimating-core" / "dist"


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
    """The bimforge version the plugins bundle."""
    wheels = sorted(BUNDLED.glob("bimforge-*.whl"))
    assert len(wheels) == 1, f"expected one bundled bimforge wheel under {BUNDLED}, found {wheels}"
    return tuple(int(x) for x in wheels[0].name.split("-")[1].split("."))


def test_no_floor_is_above_the_version_we_ship():
    shipped = _bimforge_we_ship()
    for key, spec in _bimforge_requirements():
        floor = _floor(spec)
        assert floor is not None and floor <= shipped, (
            f"{key} floors bimforge at {floor} but the plugins bundle {shipped}; "
            f"the bundled wheel would not satisfy it")


def test_the_plugins_bundle_the_floored_release():
    shipped = _bimforge_we_ship()
    floors = {_floor(s) for k, s in _bimforge_requirements() if k == "dependencies"}
    assert floors == {shipped}, (
        f"dependencies floor bimforge at {floors} but the plugins bundle {shipped}; "
        f"run scripts/build_plugin_wheel.py <plugin> --pypi bimforge")
