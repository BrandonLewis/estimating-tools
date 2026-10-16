"""Every test directory in this repo must be in CI's pytest selection.

`openworker/tests` was not, for an unknown number of releases. 255 tests sat
outside CI and the release gate, and one of them had been failing: the
OpenWorker port guard had caught a real bug — `bulk_create_assemblies` missing
from `BIDMANAGER_TOOLS`, so the ported `build-assemblies` skill shipped the name
bare and would die at call time under OpenWorker — and nobody saw it, because
`main` was green the whole time.

`port_skills.py --check` does run in CI and cannot catch that class of bug: it
proves the ported tree MATCHES what port_skills would write, which it did. Only
scanning the sources for tool-shaped names finds a name the list never had.

This test lives in `tests/` deliberately. A guard cannot police its own
inclusion — if it lived in `openworker/tests` it would stop running the moment
that directory dropped out of the selection, which is the exact failure it
exists to prevent.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (ROOT / ".github/workflows/ci.yml",
             ROOT / ".github/workflows/release.yml")

#: Directories holding tests pytest would collect, as CI names them.
_SKIP = {".git", ".venv", "build", "node_modules", "__pycache__", ".worktrees"}


def test_directories() -> set[str]:
    """Every directory under the repo that holds `test_*.py`, pruned of build
    artifacts and vendored trees, as a repo-relative path."""
    found: set[str] = set()
    for p in ROOT.rglob("test_*.py"):
        rel = p.relative_to(ROOT)
        if _SKIP & set(rel.parts):
            continue
        found.add(str(rel.parent))
    return found


def _selections() -> dict[Path, list[str]]:
    """The pytest path arguments in each workflow's test command."""
    out: dict[Path, list[str]] = {}
    for wf in WORKFLOWS:
        text = wf.read_text(encoding="utf-8")
        m = re.search(r"python -m pytest ([^\n]*?) -q", text)
        assert m, f"{wf.name}: no `python -m pytest ... -q` command found"
        out[wf] = m.group(1).split()
    return out


def test_every_test_directory_is_covered_by_both_workflows():
    dirs = test_directories()
    assert dirs, "no test directories found — the walk is broken, not the repo"
    for wf, selected in _selections().items():
        for d in sorted(dirs):
            assert any(d == s or d.startswith(s.rstrip("/") + "/")
                       for s in selected), (
                f"{wf.name} does not run {d}: its pytest selection is "
                f"{selected}. Tests there never run in CI — add the path, or "
                f"move the tests under one already selected.")


def test_the_two_workflows_select_the_same_paths():
    """A release gate weaker than CI lets a red tag build through."""
    ci, rel = (_selections()[wf] for wf in WORKFLOWS)
    assert ci == rel, (
        f"ci.yml runs {ci} but release.yml runs {rel} — the release gate must "
        "not be the weaker of the two.")
