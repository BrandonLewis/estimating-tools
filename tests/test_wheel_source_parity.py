"""The committed estimating_tools wheel ships no module the source tree lacks.

Found while preparing the public export: the bundled wheel still carried the
`ies`, `lighting` and `thermal` packages a release after their sources were
deleted. `python -m build` ran in `packages/estimating-tools/`, where a stale
`build/lib` still held the old modules, and setuptools' build_py reuses
`build/lib`. The wheel drift guard could not see it: it compares a fresh build
with the committed wheel, and both were built the same way, so they agreed.

`build_plugin_wheel.py` now clears `build/` before building. This test is the
check the drift guard structurally cannot be: it compares the committed wheel
against the SOURCE tree, so a module that exists only in the wheel fails.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packages" / "estimating-tools" / "estimating_tools"
WHEELS = sorted((ROOT / "plugins" / "estimating-core" / "dist").glob("estimating_tools-*.whl")) + sorted(
    (ROOT / "openworker" / "skills" / "_dist").glob("estimating_tools-*.whl")
)


def _source_modules() -> set[str]:
    return {
        p.relative_to(SRC.parent).as_posix()
        for p in SRC.rglob("*.py")
        if "tests" not in p.relative_to(SRC).parts and "__pycache__" not in p.parts
    }


def test_committed_wheels_ship_only_modules_the_source_tree_has():
    assert WHEELS, "no committed estimating_tools wheel found"
    src = _source_modules()
    for wheel in WHEELS:
        shipped = {n for n in zipfile.ZipFile(wheel).namelist() if n.startswith("estimating_tools/") and n.endswith(".py")}
        ghosts = sorted(shipped - src)
        assert not ghosts, (
            f"{wheel.relative_to(ROOT)} ships {len(ghosts)} module(s) with no source, e.g. {ghosts[:5]} — "
            "a stale build/ dir fed the build; rerun scripts/build_plugin_wheel.py (it now cleans build/) "
            "and openworker/port_skills.py"
        )
        missing = sorted(src - shipped)
        assert not missing, f"{wheel.relative_to(ROOT)} lacks source modules {missing[:5]}"
