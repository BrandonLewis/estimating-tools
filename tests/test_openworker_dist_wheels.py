"""`openworker/skills/_dist` holds exactly one wheel per package, and the
newest-wheel pick orders by VERSION rather than by string.

Two failures met here, both found while cleaning up R20:

1. Stale 0.1.53 + 0.1.59 copies had accumulated beside the current wheel and
   went unnoticed for several releases. That is not untidiness — every ported
   skill's ``> **Setup:**`` fallback globs this directory inside a QUOTED
   command substitution (``pip install "$(ls .../bimforge-*.whl | tail -1)"``),
   so extra matches once collapsed into a single argument full of newlines
   that pip rejects. `port_skills.py --check` compares skill TEXT and cannot
   see it; nothing else looked. This is that missing guard.

2. `install.py` picked with ``sorted(...)[-1]`` — a LEXICOGRAPHIC sort. Fine
   through 0.1.62, silently wrong the moment a three-digit patch exists,
   because "0.1.100" < "0.1.62" as strings. Ordering is numeric now.

These live in the repo-root ``tests/`` on purpose: CI's pytest paths are
``packages/... manifest tests``, so a test under ``openworker/tests/`` would
never run in CI.
"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "openworker" / "skills" / "_dist"

# Load install.py by path, matching test_openworker_tool_prefixes.py: a
# lingering `openworker/` on sys.path leaks into the session and can shadow
# later imports (order-dependent failures).
_spec = importlib.util.spec_from_file_location(
    "openworker_install", ROOT / "openworker" / "install.py")
_install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_install)

PACKAGES = ("bimforge", "estimating_tools")


def test_dist_holds_exactly_one_wheel_per_package():
    for package in PACKAGES:
        found = sorted(p.name for p in DIST.glob(f"{package}-*.whl"))
        assert len(found) == 1, (
            f"{DIST.relative_to(ROOT)} holds {len(found)} {package} wheels "
            f"({found}) — `git rm` the superseded one in the release PR. "
            "Every ported skill's Setup fallback globs this directory, and "
            "install.py installs from it.")


def _released_version(package: str) -> str:
    """The version this tree releases for ``package``.

    estimating_tools: its pyproject, present in both trees. bimforge has its
    own release line (PyPI, from BrandonLewis/BIMForge) and the public
    estimating-tools tree carries no bimforge source, so its authority is the
    wheel the estimating-core plugin bundles -- the dist copies here are copies
    of that wheel. Pinning it to estimating_tools' version would block an
    estimating_tools release that keeps the current bimforge.
    """
    if package == "estimating_tools":
        return re.search(
            r'^version = "([^"]+)"',
            (ROOT / "packages" / "estimating-tools" / "pyproject.toml").read_text(
                encoding="utf-8"), re.M).group(1)
    (bundled,) = (ROOT / "plugins" / "estimating-core" / "dist").glob(f"{package}-*.whl")
    return bundled.name.split("-")[1]


def test_dist_wheel_versions_match_the_released_version():
    for package in PACKAGES:
        version = _released_version(package)
        (wheel,) = DIST.glob(f"{package}-*.whl")
        assert wheel.name == f"{package}-{version}-py3-none-any.whl", (
            f"{wheel.name} does not carry the released version {version} — "
            "re-run `python openworker/port_skills.py` after bumping")


def test_newest_wheel_orders_numerically_not_lexicographically():
    """The regression that motivated the helper: as STRINGS "0.1.100" sorts
    BELOW "0.1.62", so a lexicographic pick would install a stale wheel the
    first time a three-digit patch ships."""
    names = ["bimforge-0.1.62-py3-none-any.whl",
             "bimforge-0.1.100-py3-none-any.whl",
             "bimforge-0.1.9-py3-none-any.whl"]
    picked = _install.newest_wheel([Path(n) for n in names])
    assert picked.name == "bimforge-0.1.100-py3-none-any.whl"


def test_newest_wheel_handles_a_single_candidate_and_empty():
    one = [Path("bimforge-0.1.62-py3-none-any.whl")]
    assert _install.newest_wheel(one) is one[0]
    assert _install.newest_wheel([]) is None


def test_newest_wheel_does_not_crash_on_an_unparseable_name():
    """A stray file that does not carry a dotted version must not take
    precedence over a real wheel, and must not raise."""
    candidates = [Path("bimforge-nightly-py3-none-any.whl"),
                  Path("bimforge-0.1.62-py3-none-any.whl")]
    assert _install.newest_wheel(candidates).name == (
        "bimforge-0.1.62-py3-none-any.whl")
