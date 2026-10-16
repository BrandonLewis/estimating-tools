"""No skill may invoke one of our tools by a bare name.

Spec: docs/superpowers/specs/2026-09-27-plugin-runtime-design.md

`PATH` was never a channel we control, and on a measured machine it carried none
of these scripts. The plugins keep their tools in their own runtime, so the only
way a skill can reach one is by naming its shim under `~/.estimating/bin/`.

The rule is defined once, in `scripts/shim_skill_paths.py`, and this suite calls
it rather than restating it: a first attempt re-implemented the pattern here and
disagreed with the rewriter in both directions -- it missed inline code spans
that wrap across lines, and it flagged headings, sentences and frontmatter
`description:` fields that merely NAME a tool.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plugin_runtime  # noqa: E402
import shim_skill_paths as shim  # noqa: E402


def _skills():
    return sorted(ROOT.glob(shim.SRC_GLOB))


def test_there_are_skills_to_check():
    assert len(_skills()) > 30


@pytest.mark.parametrize("skill", _skills(), ids=lambda p: p.parent.name)
def test_every_tool_invocation_names_its_shim(skill):
    src = skill.read_text(encoding="utf-8")
    assert shim.rewrite(src) == src, (
        f"{skill.parent.name} invokes a tool by its bare name, which is not on "
        "PATH. Run: python scripts/shim_skill_paths.py")


def test_the_shim_path_is_what_the_runtime_module_computes():
    """The one string 57 SKILL.md files hardcode. If these two ever disagree,
    every skill points at a directory that does not exist."""
    assert plugin_runtime.bin_dir() == Path(os.path.expanduser(shim.BIN))


def test_the_rule_is_idempotent():
    """A generator over hand-written prose has to be safe to re-run."""
    for skill in _skills():
        once = shim.rewrite(skill.read_text(encoding="utf-8"))
        assert shim.rewrite(once) == once, skill.parent.name


def test_naming_a_tool_is_not_invoking_it():
    """Prose must survive: a heading, a sentence and a frontmatter description
    all mention tools without running them."""
    prose = ("description: bid tabs (est-hist parse) into the bank\n"
             "# Draw a Control Sheet (est-sheets control)\n"
             "est-bim stays deterministic and never guesses.\n"
             "the `est-bim` CLI does the rollup\n")
    assert shim.rewrite(prose) == prose


def test_an_invocation_in_either_kind_of_code_is_caught():
    fenced = "```bash\nest-bim takeoff --ifc m.ifc\n```\n"
    assert shim.BIN + "est-bim takeoff" in shim.rewrite(fenced)
    inline = "run `est-bim --help` to confirm\n"
    assert shim.BIN + "est-bim --help" in shim.rewrite(inline)
    wrapped = "1. Filter: `est-schedule scope <x.xer> --resource <X>\n   -o out.json`\n"
    assert shim.BIN + "est-schedule scope" in shim.rewrite(wrapped)


def test_our_packages_never_run_on_an_ambient_interpreter():
    """The wheels are only in the plugin's runtime now, so a bare `python -c`
    importing them imports nothing."""
    assert shim.rewrite('`python -c "import estimating_tools"`') == (
        '`' + shim.BIN + 'est-python -c "import estimating_tools"`')
    # Someone else's python is their business.
    assert shim.rewrite('`python -c "import json"`') == '`python -c "import json"`'


# ---------------------------------------------------------------------------
# a guard the rewriter's own --check cannot be
# ---------------------------------------------------------------------------

def _prose_backticks(md: str) -> int:
    """Backticks outside fenced blocks."""
    n, in_fence = 0, False
    for line in md.split("\n"):
        if shim.FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            n += line.count("`")
    return n


def _all_skills():
    """Both copies: the hand-written plugin skills and the OpenWorker
    skills port_skills.py generates from them. The corruption showed up in
    both, and a porting step can damage text of its own."""
    return _skills() + sorted(ROOT.glob("openworker/skills/*/SKILL.md"))


@pytest.mark.parametrize("md", _all_skills(),
                         ids=lambda p: f"{p.parent.parent.parent.name}-{p.parent.name}")
def test_inline_code_spans_are_balanced(md):
    """Every inline span opens and closes, so prose holds an even number of
    backticks.

    Why this exists, and why `shim_skill_paths.py --check` is not enough: an
    earlier revision of the rewriter mangled a span that WRAPPED ACROSS A LINE,
    turning `... forbidden on live\\nbids; see BM #984"` into `... forbidden on
    liv` -- truncating a word and closing the span early. The fixed rewriter is
    idempotent on that output, so --check reports no drift forever. A guard that
    asks the rewriter whether the text is right cannot see damage the rewriter
    already did; this one asks the text.

    Caught in review on PR #295, in the one skill of 114 that had it.
    """
    text = md.read_text(encoding="utf-8")
    assert _prose_backticks(text) % 2 == 0, (
        f"{md.parent.name}: odd number of backticks outside fenced blocks -- an "
        "inline code span is unclosed or was truncated mid-span")
