import warnings
from pathlib import Path

from estimating_tools.profiles.loader import load

ROOT = Path(__file__).resolve().parents[1]
TMPL = ROOT / "templates" / "profile"


def test_profile_template_loads_without_dropped_fields():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prof = load([TMPL])
    # No field should be dropped (no warnings) — the starter is schema-valid.
    assert not caught, [str(w.message) for w in caught]
    tree = prof.section("folder_conventions").get("tree")
    assert tree and Path(tree).is_absolute() and Path(tree).is_file()
    assert not prof.is_empty


def test_profile_template_tree_exists():
    assert (TMPL / "trees" / "project-tree.yaml").is_file()
