"""A skill that runs a CLI needing an on-demand extra installs that extra first.

The shared runtime installs each wheel with its BASE extras only
(`plugin_runtime.BASE_EXTRAS`: bimforge[bim,draw], estimating_tools[plugin-core]).
Anything else arrives on first use through `~/.estimating/bin/ensure-extra`.
So a skill that runs a command importing a non-base extra, and never runs
`ensure-extra` for it, fails in every session with ModuleNotFoundError.
`est-letterhead` (docxtpl, the `docgen` extra) did exactly that in
draft-an-rfi and create-org-profile, under the Claude plugin and OpenCode alike
(PR #359 review).

`NEEDS_EXTRA` is curated. It came from a static import-closure scan of every
console script both wheels declare, run against a venv holding only the base
extras. These are the commands that hard-require a missing module:

- `est-letterhead` imports docxtpl -> `docgen`
- `est-bim contour-surface` builds a TIN with scipy -> `terrain`

Deliberately NOT listed: `est-bim build` imports build123d only for optional
STEP output and the true-volume post-check (it degrades without it).
build-structure and author-structure-model already run `ensure-extra solids`
for STEP. `est-bim contours` catches scipy's absence and reports NaN spot
checks. Add a row whenever a CLI gains a hard import outside the base extras.

Lives in `tests/`, so it runs in CI with the other skill guards.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted(ROOT.glob("plugins/*/skills/*/SKILL.md"))

sys.path.insert(0, str(ROOT / "plugins" / "estimating-core" / "scripts"))
import plugin_runtime  # noqa: E402

#: (console script, subcommand or None) -> (extra, owning dist, a module in
#: the extra that the command imports, the source file that imports it).
NEEDS_EXTRA = {
    ("est-letterhead", None): (
        "docgen", "estimating_tools", "docxtpl",
        "packages/estimating-tools/estimating_tools/docgen/docxtpl_engine.py"),
    ("est-bim", "contour-surface"): (
        "terrain", "bimforge", "scipy",
        "packages/bimforge/bimforge/terrain/contours.py"),
}

PYPROJECT = {"estimating_tools": ROOT / "packages/estimating-tools/pyproject.toml",
             "bimforge": ROOT / "packages/bimforge/pyproject.toml"}


def _body(text: str) -> str:
    """The skill minus its frontmatter, which describes and never runs."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _mention(script: str, sub: str | None) -> re.Pattern:
    if sub is None:
        return re.compile(rf"(?<![\w-]){re.escape(script)}(?![\w-])")
    return re.compile(rf"(?<![\w-]){re.escape(sub)}(?![\w-])")


def _invocation(script: str, sub: str | None) -> re.Pattern:
    tail = rf" {re.escape(sub)}" if sub else ""
    return re.compile(rf"~/\.estimating/bin/{re.escape(script)}{tail}(?![\w-])")


@pytest.mark.parametrize("key", sorted(NEEDS_EXTRA, key=str), ids=lambda k: " ".join(filter(None, k)))
def test_the_table_is_true(key):
    """Each row names a real script, a non-base extra of the owning wheel, and
    a module that extra provides and the command's source really imports."""
    script, _sub = key
    extra, dist, module, source = NEEDS_EXTRA[key]
    if not PYPROJECT[dist].is_file() or not (ROOT / source).is_file():
        # The public export ships bimforge as a wheel, not source; the skill
        # guard below still runs there, only this provenance check cannot.
        pytest.skip(f"{dist} source is not in this tree")
    # A regex read, not tomllib: CI still runs Python 3.10.
    toml = PYPROJECT[dist].read_text(encoding="utf-8")
    assert re.search(rf"^{re.escape(script)}\s*=", toml, re.MULTILINE), (
        f"{script} is not a {dist} console script")
    deps = re.search(rf"^{re.escape(extra)}\s*=\s*\[([^\]]*)\]", toml, re.MULTILINE)
    assert deps, f"{dist} has no `{extra}` extra"
    names = [re.split(r"[\[<>=!~ ]", d.strip().strip('"'))[0].replace("-", "_").lower()
             for d in deps.group(1).split(",") if d.strip()]
    assert module in names, f"{extra} does not provide {module} ({names})"
    assert extra not in plugin_runtime.BASE_EXTRAS[dist], (
        f"{extra} is a base extra now -- drop the row")
    assert plugin_runtime.EXTRA_OWNER.get(extra) == dist, (
        f"ensure-extra cannot install {extra}: EXTRA_OWNER does not map it to {dist}")
    text = (ROOT / source).read_text(encoding="utf-8")
    assert re.search(rf"^\s*(from|import) {module}\b", text, re.MULTILINE), (
        f"{source} no longer imports {module} -- re-check whether the row still holds")


def test_the_guard_sees_the_skills_it_is_about():
    users = {md.parent.name for md in SKILLS
             for (script, sub) in NEEDS_EXTRA
             if _mention(script, sub).search(_body(md.read_text(encoding="utf-8")))}
    assert {"draft-an-rfi", "create-org-profile", "measure-plans"} <= users, users


@pytest.mark.parametrize("md", SKILLS, ids=lambda p: p.parent.name)
def test_a_skill_installs_the_extra_before_running_the_command(md):
    body = _body(md.read_text(encoding="utf-8"))
    for (script, sub), (extra, *_rest) in NEEDS_EXTRA.items():
        if not _mention(script, sub).search(body):
            continue
        name = " ".join(filter(None, (script, sub)))
        ensure = body.find(f"~/.estimating/bin/ensure-extra {extra}")
        assert ensure != -1, (
            f"{md.parent.name} runs `{name}`, which needs the `{extra}` extra, but "
            f"never runs `~/.estimating/bin/ensure-extra {extra}` -- it fails with "
            "ModuleNotFoundError in every session")
        first = _invocation(script, sub).search(body)
        assert first is None or ensure < first.start(), (
            f"{md.parent.name}: `ensure-extra {extra}` comes after the first `{name}` "
            "call, so the first call fails")
