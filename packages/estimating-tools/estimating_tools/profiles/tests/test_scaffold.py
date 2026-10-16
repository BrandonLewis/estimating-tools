import pytest
from pathlib import Path

from estimating_tools.profiles.model import Profile
from estimating_tools.profiles.scaffold import materialize_tree


def _tree_file(tmp_path) -> Path:
    t = tmp_path / "tree.yaml"
    t.write_text("- Bid Data\n- Correspondence:\n    - Owner\n- Submittals\n")
    return t


def test_materialize_builds_tree_from_profile(tmp_path):
    tree = _tree_file(tmp_path)
    base = tmp_path / "ProjectX"; base.mkdir()
    p = Profile(data={"folder_conventions": {"tree": str(tree)}})
    built = materialize_tree(p, base, {"name": "ProjectX"})
    assert built is True
    assert (base / "Bid Data").is_dir()
    assert (base / "Correspondence" / "Owner").is_dir()
    assert (base / "Submittals").is_dir()


def test_materialize_no_folder_conventions_is_noop(tmp_path):
    base = tmp_path / "P"; base.mkdir()
    built = materialize_tree(Profile(data={}), base, {})
    assert built is False
    assert list(base.iterdir()) == []


def test_scalar_tree_raises_clear_error(tmp_path):
    tree = tmp_path / "t.yaml"; tree.write_text("just-a-string\n")
    base = tmp_path / "P"; base.mkdir()
    from estimating_tools.profiles.model import Profile
    p = Profile(data={"folder_conventions": {"tree": str(tree)}})
    with pytest.raises(ValueError):
        materialize_tree(p, base, {})
