"""Packaged canonical layouts (mirroring the Work repo's `work` CLI trees)."""
import pytest

from estimating_tools.profiles.scaffold import main, materialize_layout


def test_work_project_layout(tmp_path):
    materialize_layout(tmp_path, "work-project", {})
    for d in ("Addenda", "Plans", "Specs", "Supplemental-Info",
              "Correspondence", "Notes"):
        assert (tmp_path / d).is_dir()


def test_work_bid_layout(tmp_path):
    materialize_layout(tmp_path, "work-bid", {})
    for d in ("Estimate", "Proposal", "Subquotes", "Sheets", "BIM", "Takeoff"):
        assert (tmp_path / d).is_dir()
    assert (tmp_path / "Briefing" / "prompts").is_dir()


def test_unknown_layout_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown layout"):
        materialize_layout(tmp_path, "nope", {})


def test_traversal_layout_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown layout"):
        materialize_layout(tmp_path, "work-project/../work-bid", {})


def test_cli_layout_flag(tmp_path):
    rc = main(["Job X", "--parent", str(tmp_path), "--layout", "work-project"])
    assert rc == 0
    assert (tmp_path / "Job X" / "Plans").is_dir()


def test_cli_unknown_layout_fails_cleanly(tmp_path):
    rc = main(["Job X", "--parent", str(tmp_path), "--layout", "nope"])
    assert rc == 1
