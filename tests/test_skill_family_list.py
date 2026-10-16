"""The build-structure skill's family table must match the shipped registry.

#304: the skill hardcoded 8 of the 14 families `available()` returns. It even said
"that command is the authority — this list drifts, the registry does not", and the
list drifted anyway. A later session read the list, concluded there was no
modelling route for a bridge that seven families already covered, and hand-briefed
a bespoke build. Telling a reader a list is untrustworthy does not stop them
trusting it; the fix is for the list to be right.

So the table stays (an agent that never runs the command still needs to see the
families) and this makes it honest. Both directions matter:

* a family the registry gained and the table never named — the one that caused
  #304;
* a family the table names that the registry does not have — the reader goes
  looking for something that is not there.

A third test asserts the table's marker is present, so deleting the table fails
rather than silently retiring the gate: a passing test over nothing is the shape
of bug that let the openworker `_dist` wheel go stale for weeks.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "calc-bim" / "skills" / "build-structure" / "SKILL.md"

#: The sentence introducing the table. Visible prose, not an HTML comment: a
#: comment parses just as well and is invisible to the reader, which is how it
#: would drift from the table they actually believe.
MARKER = "shipped families, by what they model"


def shipped_families() -> set[str]:
    """The BUILT-IN families, which is what the table documents.

    Deliberately `_shipped()` and not `available()`: `available()` is `_shipped()`
    plus every installed `bimforge.families` entry point, so a consumer that
    legitimately registers a bid-side family package would make THIS repo's test
    fail by reporting their family as missing documentation here. The gate has to
    be scoped to the set the table claims to cover.
    """
    from bimforge.author.families.registry import _shipped

    return set(_shipped())


def tabled_families(text: str) -> set[str]:
    """Backticked tokens inside the family table, which runs from MARKER to the
    first line after it that is not a table row or blank."""
    start = text.find(MARKER)
    if start < 0:
        return set()
    found: set[str] = set()
    for line in text[start:].splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            break
        found.update(re.findall(r"`([a-z][a-z0-9-]*)`", stripped))
    return found


def test_the_skill_file_exists():
    assert SKILL.is_file(), SKILL


def test_the_table_marker_is_present():
    """Deleting the table must fail here, not quietly stop the comparison."""
    assert MARKER in SKILL.read_text(encoding="utf-8"), (
        f"{SKILL.name} no longer says {MARKER!r}, so nothing compares its family "
        "table to the registry. Restore the table and its introduction.")


def test_the_registry_returns_families_at_all():
    """Guards the comparison: an empty registry would make it pass vacuously."""
    assert len(shipped_families()) >= 10


def test_a_registered_bid_side_family_is_not_a_table_omission():
    """`available()` may exceed the table and that is correct, not a gap."""
    from bimforge.author.families.registry import available

    assert shipped_families() <= set(available())


def test_the_skill_table_and_the_registry_agree():
    tabled = tabled_families(SKILL.read_text(encoding="utf-8"))
    shipped = shipped_families()
    missing = sorted(shipped - tabled)
    extra = sorted(tabled - shipped)
    assert not missing, (
        f"{SKILL.name}'s family table does not name {missing}, which "
        f"available() returns. This is #304 exactly: a reader takes the table "
        f"for the whole set and concludes a structure has no modelling route.")
    assert not extra, (
        f"{SKILL.name}'s family table names {extra}, which available() does not "
        f"return. A reader will go looking for a family that is not there.")


def test_the_table_does_not_claim_a_stale_count():
    """The prose states a number. If the registry grows, the number has to move
    with it — otherwise the table is right and the sentence above it is wrong."""
    text = SKILL.read_text(encoding="utf-8")
    stated = re.search(r"The (\d+) shipped families", text)
    assert stated, "the table's introduction no longer states a count"
    assert int(stated.group(1)) == len(shipped_families()), (
        f"the skill says {stated.group(1)} shipped families; available() returns "
        f"{len(shipped_families())}")
