"""Briefing pack: skeletons with frontmatter, created-once semantics."""
import pytest
import yaml

from estimating_tools.intake.briefing import build_briefing_pack
from estimating_tools.intake.manifest import BidFrameItem, ProjectManifest

STRUCTURES = [
    {"id": "headwall-type-1", "name": "Headwall Type 1", "count": 30,
     "cost_codes": ["03 30 00"], "bid_items": [{"item_number": "0010", "schedule": "A"}]},
    {"id": "outfall-2", "name": "Outfall No. 2"},
]


def _manifest():
    m = ProjectManifest(name="Job X", organization_id=7, bm_project_id=42)
    m.set_bid_frame([BidFrameItem(item_number="0010", schedule="A",
                                  item_code="03 30 00", unit="CY")],
                    snapshot_at="2026-08-02T12:00:00+00:00")
    return m


def test_pack_files_created(tmp_path):
    created = build_briefing_pack(_manifest(), STRUCTURES, tmp_path)
    names = {p.relative_to(tmp_path).as_posix() for p in created}
    assert names == {"Briefing/scope.md", "Briefing/risks.md",
                     "Briefing/structures.yaml",
                     "Briefing/prompts/headwall-type-1.md",
                     "Briefing/prompts/outfall-2.md"}


def test_prompt_frontmatter_carries_pricing_and_rollup_keys(tmp_path):
    build_briefing_pack(_manifest(), STRUCTURES, tmp_path)
    text = (tmp_path / "Briefing" / "prompts" / "headwall-type-1.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["structure_id"] == "headwall-type-1"
    assert fm["project"] == "Job X"
    assert fm["organization_id"] == 7
    assert fm["count"] == 30
    assert fm["bid_items"] == [{"item_number": "0010", "schedule": "A"}]
    assert fm["cost_codes"] == ["03 30 00"]


def test_default_count_is_one(tmp_path):
    build_briefing_pack(_manifest(), STRUCTURES, tmp_path)
    text = (tmp_path / "Briefing" / "prompts" / "outfall-2.md").read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["count"] == 1


def test_existing_files_never_overwritten(tmp_path):
    (tmp_path / "Briefing").mkdir()
    (tmp_path / "Briefing" / "scope.md").write_text("agent prose", encoding="utf-8")
    created = build_briefing_pack(_manifest(), STRUCTURES, tmp_path)
    assert (tmp_path / "Briefing" / "scope.md").read_text(encoding="utf-8") == "agent prose"
    assert not any(p.name == "scope.md" for p in created)


def test_structures_yaml_lists_structures(tmp_path):
    build_briefing_pack(_manifest(), STRUCTURES, tmp_path)
    data = yaml.safe_load((tmp_path / "Briefing" / "structures.yaml").read_text(encoding="utf-8"))
    assert [s["id"] for s in data["structures"]] == ["headwall-type-1", "outfall-2"]


def test_rejects_path_escaping_id(tmp_path):
    with pytest.raises(ValueError, match="invalid structure id"):
        build_briefing_pack(_manifest(), [{"id": "../evil"}], tmp_path)
    assert not (tmp_path / "Briefing").exists()   # fail fast: nothing written


def test_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicate structure id"):
        build_briefing_pack(_manifest(), [{"id": "s1"}, {"id": "s1"}], tmp_path)


def test_rerun_adding_structure_keeps_structures_yaml_in_sync(tmp_path):
    build_briefing_pack(_manifest(), [STRUCTURES[0]], tmp_path)
    created = build_briefing_pack(_manifest(), STRUCTURES, tmp_path)
    data = yaml.safe_load(
        (tmp_path / "Briefing" / "structures.yaml").read_text(encoding="utf-8"))
    assert {s["id"] for s in data["structures"]} == {"headwall-type-1", "outfall-2"}
    names = {p.name for p in created}
    assert names == {"structures.yaml", "outfall-2.md"}   # scope/risks/s1 prompt untouched
