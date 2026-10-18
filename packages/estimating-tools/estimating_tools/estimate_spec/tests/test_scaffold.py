"""Bridge 1 + Bridge 3 (scaffold.py + `est-estimate scaffold`).

Every generated spec must pass full-schema validation AND render through
build.generate — a scaffold that won't render is a bug. The sample-bridge fixtures are
synthetic (item numbers/quantities from the public bid schedule); the real
project files never appear here.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.build import generate
from estimating_tools.estimate_spec.cli import main as cli_main
from estimating_tools.estimate_spec.format_pack import FormatPackError, load_pack
from estimating_tools.estimate_spec.scaffold import (
    PLACEHOLDER_GEOMETRY_LABEL, content_hash, is_hand_edited, is_mob_item,
    load_profile_scaffolds, load_scaffolds_file, merge_scaffold, scaffold_spec,
    select_items, validate_scaffold_entries, validate_spec)
from estimating_tools.intake.bid_frame import normalize_bid_items
from estimating_tools.intake.manifest import ProjectManifest

FIXTURES = Path(__file__).parent / "fixtures"
ES = fp.ENGINE_DIR
LEGACY_DIR = ES / "tests" / "fixtures" / "packs" / "legacy_demo"
ALT_DIR = FIXTURES / "packs" / "alt"

_MIN_PACK_MANIFEST = """\
name: {name}
version: 1
files:
  units: units.yaml
  tokens: tokens.yaml
  recipes: recipes.yaml
  vocabulary: vocabulary.yaml
  seed: seed.yaml
"""


@pytest.fixture(scope="module")
def demo_pack():
    return fp.load_pack(LEGACY_DIR)


@pytest.fixture(scope="module")
def alt_pack():
    return fp.load_pack(ALT_DIR)


def _min_bid_items() -> ProjectManifest:
    """A bid frame with exactly one mobilization-class (rate-host) item —
    enough to exercise pack-driven recipe/sheet naming without tripping a
    pack's own takeoff requirement on its default item recipe."""
    raw = [{"item_number": "1", "description": "Mobilization", "unit": "LS",
            "estimated_quantity": 1, "schedule": "Base Bid"}]
    m = ProjectManifest(name="Min Pack Check", organization_id=0)
    m.set_bid_frame(normalize_bid_items(raw), snapshot_at="2026-01-01T00:00:00+00:00")
    return m


def _non_mob_bid_items() -> ProjectManifest:
    """A single non-mobilization item, selected via items='all' (it has no
    owning structure, so the default 'structures' selection would drop it)."""
    raw = [{"item_number": "2", "description": "Install 24-in RCP", "unit": "LF",
            "estimated_quantity": 100, "schedule": "Base Bid"}]
    m = ProjectManifest(name="Non-Mob Pack Check", organization_id=0)
    m.set_bid_frame(normalize_bid_items(raw), snapshot_at="2026-01-01T00:00:00+00:00")
    return m


def _write_min_pack(tmp_path: Path, name: str = "copy", *, scaffold: dict | None = None,
                    drop: tuple = (), seed_drop: tuple = ()) -> Path:
    """A copy of the demo pack with `scaffold` merged over its seed.scaffold.

    Merged, not substituted: every key in `_SCAFFOLD_KEYS` is required now, so
    a test that means to vary one key must not silently drop the other five.
    `drop` removes seed.scaffold keys; `seed_drop` removes whole seed blocks.
    """
    root = tmp_path / name
    root.mkdir(parents=True)
    for f in ("units.yaml", "tokens.yaml", "recipes.yaml", "vocabulary.yaml", "seed.yaml"):
        shutil.copy(LEGACY_DIR / f, root / f)
    (root / "format.yaml").write_text(_MIN_PACK_MANIFEST.format(name=name), encoding="utf-8")
    seed_path = root / "seed.yaml"
    doc = yaml.safe_load(seed_path.read_text(encoding="utf-8"))
    doc["scaffold"] = {**doc["scaffold"], **(scaffold or {})}
    for key in drop:
        doc["scaffold"].pop(key, None)
    for key in seed_drop:
        doc.pop(key, None)
    seed_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# pack-driven scaffold: recipes, sheet prefixes, slot, placeholder takeoff
# ---------------------------------------------------------------------------

def test_scaffold_uses_pack_recipe_names(demo_pack):
    spec = scaffold_spec(_min_bid_items(), pack=demo_pack).spec
    recipes = {it["recipe"] for it in spec["items"]}
    assert recipes <= {"setup", "line_item"}          # demo's names, not mob_item
    assert "mob_item" not in recipes


def test_scaffolded_demo_spec_validates_against_demo_pack(demo_pack):
    spec = scaffold_spec(_min_bid_items(), pack=demo_pack).spec
    validate_spec(spec, pack=demo_pack)               # must not raise


def test_seed_scaffold_recipe_must_exist(tmp_path):
    pack_dir = _write_min_pack(tmp_path, scaffold={"default_item_recipe": "nope",
                                                    "rate_host_recipe": "setup"})
    with pytest.raises(FormatPackError, match="nope"):
        load_pack(pack_dir)


def test_seed_scaffold_placeholder_takeoff_kind_must_be_known(tmp_path):
    pack_dir = _write_min_pack(tmp_path, scaffold={
        "default_item_recipe": "line_item",
        "rate_host_recipe": "setup",
        "placeholder_takeoff": {"kind": "nonsense-kind", "fields": []},
    })
    with pytest.raises(FormatPackError, match="nonsense-kind"):
        load_pack(pack_dir)


def test_pack_with_no_placeholder_takeoff_omits_takeoff_on_non_mob_items(demo_pack):
    """The demo pack declares no seed.scaffold.placeholder_takeoff — a
    scaffolded NON-mob item (the pack's default_item_recipe, 'line_item')
    must carry no `takeoff` key at all, not an empty dict, not null. (That
    item would then fail the demo pack's own schema, which requires a
    takeoff for line_item — correct; scaffolding doesn't validate.)"""
    spec = scaffold_spec(_non_mob_bid_items(), items="all", pack=demo_pack).spec
    item = next(it for it in spec["items"] if it["item_no"] == "2")
    assert item["recipe"] == "line_item"
    assert "takeoff" not in item


def sample_bridge_manifest() -> ProjectManifest:
    raw = json.loads((FIXTURES / "sample_bridge_bid_items.json").read_text(encoding="utf-8"))
    m = ProjectManifest(name="Sample Bridge", organization_id=0,
                        project_ref="sample-bridge",
                        bid_date="2026-08-12")
    m.set_bid_frame(normalize_bid_items(raw), snapshot_at="2026-08-02T00:00:00+00:00")
    return m


def sample_bridge_structures() -> list:
    doc = yaml.safe_load((FIXTURES / "sample_bridge_structures.yaml").read_text(encoding="utf-8"))
    return doc["structures"]


# ---------------------------------------------------------------------------
# classification + selection
# ---------------------------------------------------------------------------

def test_mob_by_description_regex_requires_ls():
    assert is_mob_item({"unit": "LS", "description": "Mobilization"})
    assert is_mob_item({"unit": "ls", "description": "MOBILISATION (MAX 10%)"})
    assert not is_mob_item({"unit": "EA", "description": "Mobilization"})
    assert not is_mob_item({"unit": "LS", "description": "Clearing and Grubbing"})


def test_mob_by_org_profile_code_wins_without_regex_hit():
    entry = {"unit": "LS", "description": "Move-in / Move-out", "item_code": "999990"}
    assert is_mob_item(entry, mob_codes=("999990",))
    assert not is_mob_item(entry)


def test_select_structures_default_is_rollups_plus_mob():
    picked = select_items(sample_bridge_manifest().bid_frame, sample_bridge_structures(), "structures")
    numbers = [e.item_number for e, _ in picked]
    assert numbers == ["2217-1", "2217-38", "2217-39", "2217-40"]
    sids = {e.item_number: sid for e, sid in picked}
    assert sids["2217-38"] == "38c0366"
    assert sids["2217-1"] is None


def test_select_all_takes_the_whole_schedule():
    picked = select_items(sample_bridge_manifest().bid_frame, sample_bridge_structures(), "all")
    assert len(picked) == 10


def test_select_csv_cherry_picks_and_always_keeps_mob():
    picked = select_items(sample_bridge_manifest().bid_frame, [], "2217-38,2217-39")
    assert [e.item_number for e, _ in picked] == ["2217-1", "2217-38", "2217-39"]


def test_select_csv_unknown_item_number_errors():
    with pytest.raises(ValueError, match="2217-99"):
        select_items(sample_bridge_manifest().bid_frame, [], "2217-99")


# ---------------------------------------------------------------------------
# scaffold_spec — the generated skeleton
# ---------------------------------------------------------------------------

def test_scaffold_validates_and_builds(alt_pack):
    result = scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(), pack=alt_pack)
    spec = result.spec
    validate_spec(spec, pack=alt_pack)       # full-schema + cross references
    wb = generate(spec, alt_pack)            # and it renders — no frame surgery
    # "PRE" is the alt pack's own rate-host prefix (seed.scaffold.rate_host_prefix);
    # "38c0366" is the structure id from sample_bridge_structures.yaml, pack-agnostic.
    assert f"{alt_pack.seed['scaffold']['rate_host_prefix']} 2217-1" in wb.sheetnames
    assert "38c0366 2217-38" in wb.sheetnames


def test_scaffold_recipes_and_placeholder_geometry(alt_pack):
    spec = scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(), pack=alt_pack).spec
    by_no = {it["item_no"]: it for it in spec["items"]}
    sc = alt_pack.seed["scaffold"]
    assert by_no["2217-1"]["recipe"] == sc["rate_host_recipe"]
    assert "takeoff" not in by_no["2217-1"]
    deck = by_no["2217-40"]
    assert deck["recipe"] == sc["default_item_recipe"]
    assert deck["takeoff"]["kind"] == "geometry"
    line = deck["takeoff"]["lines"][0]
    assert line["label"] == PLACEHOLDER_GEOMETRY_LABEL
    # ftg_cy/wall_cy are locked field names (summarize.py/artifact.py hardcode
    # them) — see the alt pack's vocabulary.yaml provenance note.
    assert line["ftg_cy"] == 0 and line["wall_cy"] == 0


def test_scaffold_qty_is_the_official_agency_figure(alt_pack):
    spec = scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(), pack=alt_pack).spec
    ftg = next(it for it in spec["items"] if it["item_no"] == "2217-38")
    assert ftg["qty"] == 30.0
    assert any("OFFICIAL agency schedule quantity" in n for n in ftg["notes"])
    assert ftg["uom"] == "CY"
    assert ftg["cost_code"] == "FTG-CONC"


def test_scaffold_meta_provenance_and_hashes(alt_pack):
    spec = scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(),
                         generated_at="2026-08-02T00:00:00+00:00", pack=alt_pack).spec
    ftg = next(it for it in spec["items"] if it["item_no"] == "2217-38")
    meta = ftg["scaffold_meta"]
    assert meta["source"] == "bid_frame"
    assert meta["schedule"] == "Base Bid"
    assert meta["official_qty"] == 30.0
    assert meta["generated_at"] == "2026-08-02T00:00:00+00:00"
    for f in ("description", "uom", "qty", "takeoff", "labor"):
        assert meta["field_hashes"][f] == content_hash(ftg[f])
    assert not is_hand_edited(ftg)
    ftg["qty"] = 31
    assert is_hand_edited(ftg)


def test_scaffold_without_mob_item_injects_rate_host_and_builds(alt_pack):
    m = sample_bridge_manifest()
    m.bid_frame = [i for i in m.bid_frame if i.item_number != "2217-1"]
    result = scaffold_spec(m, sample_bridge_structures(), pack=alt_pack)
    assert result.injected_rate_host
    host = result.spec["items"][0]
    assert host["recipe"] == alt_pack.seed["scaffold"]["rate_host_recipe"]
    assert host["item_no"] == "RATES"
    validate_spec(result.spec, pack=alt_pack)
    generate(result.spec, alt_pack)


def test_scaffold_no_bid_frame_errors():
    m = ProjectManifest(name="Empty")
    with pytest.raises(ValueError, match="bid frame"):
        scaffold_spec(m, pack=fp.load_pack(LEGACY_DIR))


def test_sheet_names_fit_excel(alt_pack):
    m = sample_bridge_manifest()
    structures = sample_bridge_structures()
    structures[0]["id"] = "a-very-long-structure-identifier-indeed"
    spec = scaffold_spec(m, structures, pack=alt_pack).spec
    for it in spec["items"]:
        assert len(it["sheet"]) <= 31


# ---------------------------------------------------------------------------
# Bridge 3 — scaffold entries: validation + precedence
# ---------------------------------------------------------------------------

# Trades/cost-block name are the alt pack's own (FITTER/RIGGER, VENDOR —
# a line-priced block with no header-price convention).
FTG_ENTRY = {
    "item_code": "FTG-CONC",
    "source": "bm:scaffold:17",
    "labor": [{
        "slot": "AA", "description": "Footings - form/strip",
        "activities": [{"name": "Form", "factor": 0.25},
                       {"name": "Strip", "factor": 0.25}],
        "crew": [{"trade": "FITTER", "count": 1, "days": 0},
                 {"trade": "RIGGER", "count": 2, "days": 0}],
    }],
    "cost_details": [{"name": "VENDOR",
                      "lines": [{"name": "PICKUP", "uom": "Hrs", "qty": 0,
                                 "unit_price": 15}]}],
}


def test_scaffold_entry_prefills_labor_and_records_source(alt_pack):
    result = scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(),
                           scaffold_entries={"FTG-CONC": FTG_ENTRY}, pack=alt_pack)
    spec = result.spec
    ftg = next(it for it in spec["items"] if it["item_no"] == "2217-38")
    assert ftg["labor"][0]["description"] == "Footings - form/strip"
    assert ftg["cost_details"][0]["name"] == "VENDOR"
    assert ftg["scaffold_meta"]["source"] == "bm:scaffold:17"
    assert ("2217-38", "bm:scaffold:17") in result.prefilled
    validate_spec(spec, pack=alt_pack)
    generate(spec, alt_pack)


def test_scaffold_entry_crews_spliced_to_top_level(alt_pack):
    entry = dict(FTG_ENTRY)
    entry["crews"] = [{"id": "FTG-CREW",
                       "members": [{"trade": "FITTER", "count": 1},
                                   {"trade": "RIGGER", "count": 2}]}]
    spec = scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(),
                         scaffold_entries={"FTG-CONC": entry}, pack=alt_pack).spec
    assert [c["id"] for c in spec["crews"]] == ["FTG-CREW"]
    validate_spec(spec, pack=alt_pack)


def test_validate_scaffold_entries_rejects_missing_source():
    with pytest.raises(ValueError, match="source"):
        validate_scaffold_entries([{"item_code": "X"}], pack=fp.load_pack(LEGACY_DIR))


def test_validate_scaffold_entries_rejects_bad_labor_block():
    bad = {"item_code": "X", "source": "bm:scaffold:1",
           "labor": [{"slot": "a lowercase slot", "description": "d",
                      "crew": [{"trade": "FITTER", "days": 0}]}]}
    with pytest.raises(ValueError, match="invalid scaffold entry"):
        validate_scaffold_entries([bad], pack=fp.load_pack(LEGACY_DIR))


def test_validate_scaffold_entries_rejects_non_list():
    with pytest.raises(ValueError, match="expected a list"):
        validate_scaffold_entries({"item_code": "X"})


def test_load_scaffolds_file_and_profile_precedence(tmp_path, alt_pack):
    profile_dir = tmp_path / "org-profile"
    profile_dir.mkdir()
    profile_entry = dict(FTG_ENTRY, source="will-be-defaulted")
    del profile_entry["source"]
    (profile_dir / "estimate_scaffolds.yaml").write_text(
        yaml.safe_dump({"scaffolds": [profile_entry]}), encoding="utf-8")
    prof = load_profile_scaffolds([profile_dir], pack=alt_pack)
    assert prof["FTG-CONC"]["source"] == "profile:estimate_scaffolds.yaml"

    bm_file = tmp_path / "scaffolds.json"
    bm_file.write_text(json.dumps([FTG_ENTRY]), encoding="utf-8")
    bm = load_scaffolds_file(bm_file, pack=alt_pack)
    merged = {**prof, **bm}      # the CLI's precedence: BM catalog wins
    assert merged["FTG-CONC"]["source"] == "bm:scaffold:17"


# ---------------------------------------------------------------------------
# --merge semantics + refuse-to-clobber (CLI level)
# ---------------------------------------------------------------------------

def _write_sample_bridge_inputs(tmp_path) -> tuple[Path, Path]:
    mpath = tmp_path / "manifest.json"
    sample_bridge_manifest().save(mpath)
    spath = tmp_path / "structures.yaml"
    spath.write_text((FIXTURES / "sample_bridge_structures.yaml").read_text(encoding="utf-8"),
                     encoding="utf-8")
    return mpath, spath


def test_cli_scaffold_writes_valid_spec(tmp_path, capsys, alt_pack):
    mpath, spath = _write_sample_bridge_inputs(tmp_path)
    out = tmp_path / "sample-bridge.estimate.yaml"
    # --format is required here: the demo pack declares no
    # seed.scaffold.placeholder_takeoff, so a scaffolded non-mob item has no
    # takeoff and fails the demo pack's own schema (by design — demo expects
    # the estimator to fill geometry by hand). The alt pack DOES declare one.
    rc = cli_main(["scaffold", "--manifest", str(mpath), "--structures", str(spath),
                   "--format", str(ALT_DIR), "-o", str(out)])
    assert rc == 0
    spec = yaml.safe_load(out.read_text(encoding="utf-8"))
    validate_spec(spec, pack=alt_pack)
    assert len(spec["items"]) == 4


def test_cli_scaffold_refuses_to_clobber_without_merge(tmp_path):
    mpath, spath = _write_sample_bridge_inputs(tmp_path)
    out = tmp_path / "sample-bridge.estimate.yaml"
    assert cli_main(["scaffold", "--manifest", str(mpath), "--structures", str(spath),
                     "--format", str(ALT_DIR), "-o", str(out)]) == 0
    assert cli_main(["scaffold", "--manifest", str(mpath), "--structures", str(spath),
                     "--format", str(ALT_DIR), "-o", str(out)]) == 2


def test_cli_scaffold_merge_updates_unedited_and_keeps_hand_edits(tmp_path, alt_pack):
    mpath, spath = _write_sample_bridge_inputs(tmp_path)
    out = tmp_path / "sample-bridge.estimate.yaml"
    assert cli_main(["scaffold", "--manifest", str(mpath), "--structures", str(spath),
                     "--format", str(ALT_DIR), "-o", str(out)]) == 0
    spec = yaml.safe_load(out.read_text(encoding="utf-8"))
    for it in spec["items"]:
        if it["item_no"] == "2217-38":
            it["qty"] = 31.5                       # hand edit — must survive merge
        if it["item_no"] == "2217-39":
            it["labor"][0]["crew"][0]["days"] = 4  # hand-edited labor — survives
    out.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

    # the bid frame moves: official qty for 2217-40 changes
    manifest = ProjectManifest.load(mpath)
    for entry in manifest.bid_frame:
        if entry.item_number == "2217-40":
            entry.estimated_quantity = 74.0
    manifest.save(mpath)

    assert cli_main(["scaffold", "--manifest", str(mpath), "--structures", str(spath),
                     "--format", str(ALT_DIR), "--merge", "-o", str(out)]) == 0
    merged = yaml.safe_load(out.read_text(encoding="utf-8"))
    by_no = {it["item_no"]: it for it in merged["items"]}
    assert by_no["2217-38"]["qty"] == 31.5                       # hand edit kept
    assert by_no["2217-39"]["labor"][0]["crew"][0]["days"] == 4  # hand edit kept
    assert by_no["2217-40"]["qty"] == 74.0                       # scaffold-owned updated
    validate_spec(merged, pack=alt_pack)


def test_merge_adds_new_items_and_keeps_existing():
    fresh = scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(),
                          pack=fp.load_pack(LEGACY_DIR)).spec
    existing = {"project": "X", "markup": 0, "rate_table": fresh["rate_table"],
                "items": [dict(fresh["items"][0])]}
    hand = {"recipe": "work_item", "sheet": "HAND 1", "item_no": "HAND-1",
            "description": "hand-authored", "uom": "LS",
            "takeoff": {"kind": "geometry",
                        "lines": [{"label": "x", "length": 1, "ftg_cy": 1,
                                   "wall_cy": 0, "wall_cf": 0}]},
            "labor": [{"slot": "AA", "description": "d",
                       "crew": [{"trade": "FITTER", "days": 1}]}]}
    existing["items"].append(hand)
    merged, report = merge_scaffold(existing, fresh)
    nos = [it["item_no"] for it in merged["items"]]
    assert "HAND-1" in nos and set(report.added) == {"2217-38", "2217-39", "2217-40"}
    assert "HAND-1" in report.kept


# ---------------------------------------------------------------------------
# the seed's rate-table trades carry their kind (fieldbook phase 3b)
# ---------------------------------------------------------------------------

def test_scaffold_writes_each_seed_trade_with_its_kind(tmp_path):
    from estimating_tools.estimate_spec.tests._packs import patched_pack

    def seed(doc):
        doc["rate_table_trades"].append({"trade": "LOADER", "kind": "equipment"})

    pack = patched_pack(tmp_path, seed=seed)
    spec = scaffold_spec(_min_bid_items(), pack=pack).spec
    assert spec["rate_table"][0] == {"trade": "SUPR", "rate": 0}     # a bare name: labor, as before
    assert spec["rate_table"][-1] == {"trade": "LOADER", "rate": 0, "kind": "equipment"}
    validate_spec(spec, pack=pack)


def test_scaffold_carries_the_seeds_cost_codes_as_the_org_code_list(demo_pack):
    spec = scaffold_spec(_min_bid_items(), pack=demo_pack).spec
    assert spec["cost_codes"] == demo_pack.seed["cost_codes"]
    assert spec["cost_codes"] is not demo_pack.seed["cost_codes"]      # a copy, never the pack's own
    validate_spec(spec, pack=demo_pack)


def test_scaffold_writes_no_cost_codes_when_the_seed_has_none(tmp_path):
    pack = fp.load_pack(_write_min_pack(tmp_path, seed_drop=("cost_codes",)))
    assert "cost_codes" not in scaffold_spec(_min_bid_items(), pack=pack).spec
