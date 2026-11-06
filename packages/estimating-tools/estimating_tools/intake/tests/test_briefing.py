"""Briefing pack: skeletons with frontmatter, created-once semantics."""
import pytest
import yaml

from estimating_tools.intake.briefing import build_briefing_pack, routing_notes
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


ROUTED = [
    {"id": "culvert-a", "name": "Culvert A", "family": "box-culvert", "route": "family"},
    {"id": "bridge-1", "name": "Bridge 1", "family": "bridge-standard", "route": "federated"},
    {"id": "vault", "name": "Vault", "route": "bespoke"},
    {"id": "outfall-2", "name": "Outfall No. 2"},
]


def _frontmatter(base, sid):
    text = (base / "Briefing" / "prompts" / f"{sid}.md").read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---")[1])


def test_family_and_route_reach_the_prompt_frontmatter(tmp_path):
    build_briefing_pack(_manifest(), ROUTED, tmp_path)
    assert _frontmatter(tmp_path, "culvert-a")["family"] == "box-culvert"
    assert _frontmatter(tmp_path, "bridge-1")["route"] == "federated"
    assert "family" not in _frontmatter(tmp_path, "vault")


def test_a_structure_without_family_or_route_writes_the_frontmatter_it_always_did(tmp_path):
    build_briefing_pack(_manifest(), STRUCTURES, tmp_path)
    assert list(_frontmatter(tmp_path, "headwall-type-1")) == [
        "structure_id", "project", "organization_id", "bm_project_id", "count",
        "bid_items", "cost_codes"]


@pytest.mark.parametrize("entry, message", [
    ({"id": "a", "route": "hand-math"}, "invalid route 'hand-math'"),
    ({"id": "a", "route": "family"}, "route 'family' names no family"),
    ({"id": "a", "route": "federated"}, "route 'federated' names no family"),
    ({"id": "a", "family": "Box Culvert"}, "invalid family 'Box Culvert'"),
])
def test_a_bad_route_or_family_is_refused(tmp_path, entry, message):
    with pytest.raises(ValueError, match=message):
        build_briefing_pack(_manifest(), [entry], tmp_path)
    assert not (tmp_path / "Briefing").exists()


def test_routing_notes_name_unrouted_structures_and_unknown_families():
    known = {"box-culvert", "bridge-standard"}
    assert routing_notes(ROUTED, known) == [
        "no modelling route: outfall-2 (set route: family | bespoke | federated)"]
    odd = ROUTED + [{"id": "piles", "family": "soldier-pile-wall", "route": "family"}]
    assert routing_notes(odd, known)[1] == (
        "family not in bimforge's registry: piles (soldier-pile-wall) "
        "(a consumer repo's own family, or a typo)")
    assert routing_notes(odd, None) == routing_notes(ROUTED, known)
    assert routing_notes(ROUTED[:3], known) == []
