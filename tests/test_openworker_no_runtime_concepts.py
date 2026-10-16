"""Ported OpenWorker skills never explain themselves with plugin-runtime words.

OpenWorker has no plugin runtime, no SessionStart hook, and no shim directory:
its setup line pip-installs the two wheels into the interpreter the agent is
already running. So a ported skill that says "the shared runtime", "if the shim
is missing", or "run `python <plugin-root>/scripts/ensure_tools.py`" is telling
an OpenWorker user to do something impossible, in the one paragraph they read
when something is already broken.

Caught in review on PR #295: the runtime change rewrote 11 calc-bim
Prerequisites blocks in plugin terms, and `port_skills.py` had no reason to
touch them, so all 11 shipped that way. `build-structure` ended up saying "If
the shim is missing" to a reader with no shims.

The fix is in the skills, not in the porter. `port_skills.py` translates what is
MECHANICAL — tool namespacing, the setup line, shim paths — and an earlier
attempt to have it rewrite hand-written prose is what corrupted a warning in
push-takeoff (see test_inline_code_spans_are_balanced). So Prerequisites blocks
now state the requirement and defer the mechanism to the **Setup** block, which
IS translated per context. This test pins that discipline on the committed port.

`~/.estimating` and `ensure-extra` are allowed, but only inside an explicitly
labelled "Under the plugins" clause: the heavy extras have no single instruction
true in both worlds, so those two skills name both and label which is which.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PORTED = sorted((ROOT / "openworker" / "skills").glob("*/SKILL.md"))

#: Phrases that describe machinery OpenWorker does not have.
FORBIDDEN = (
    "shared runtime",
    "the shim is missing",
    "ensure_tools.py",
    "<plugin-root>",
    "plugin root",
    "SessionStart",
)

#: Plugin-only strings a ported skill may still carry, provided the surrounding
#: text says which environment the clause is about. Keyed by the marker that
#: must appear in the same paragraph.
CONDITIONED = {"~/.estimating": "Under the plugins",
               "ensure-extra": "Under the plugins"}


def test_there_are_ported_skills_to_check():
    assert len(PORTED) > 30


@pytest.mark.parametrize("md", PORTED, ids=lambda p: p.parent.name)
def test_no_plugin_runtime_machinery_in_a_ported_skill(md):
    text = md.read_text(encoding="utf-8")
    found = [p for p in FORBIDDEN if p in text]
    assert not found, (
        f"{md.parent.name} explains itself with machinery OpenWorker has "
        f"none of: {found}. State the requirement and defer the mechanism to "
        "the Setup block, which port_skills.py rewrites per environment.")


@pytest.mark.parametrize("md", PORTED, ids=lambda p: p.parent.name)
def test_plugin_only_commands_are_labelled_as_such(md):
    """A ported skill may name `ensure-extra` only in a paragraph that says the
    clause is about the plugins, and must then also give the pip form."""
    for paragraph in md.read_text(encoding="utf-8").split("\n\n"):
        for needle, marker in CONDITIONED.items():
            if needle in paragraph:
                assert marker in paragraph, (
                    f"{md.parent.name}: {needle!r} appears with no "
                    f"{marker!r} label, so an OpenWorker reader cannot tell "
                    "the instruction is not theirs")
                assert "pip install" in paragraph, (
                    f"{md.parent.name}: {needle!r} is labelled but the "
                    "paragraph gives no pip alternative, so an OpenWorker "
                    "reader is left with no way to do it")
