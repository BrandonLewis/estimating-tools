"""Bridge 2 (apply.py + `est-estimate apply-takeoff`).

The sample-bridge numbers are the Phase 4 exit criterion: deck / footing / stem+wing
items carry 75.00 / 29.63 / 104.44 CY with geometry lines whose CY totals
match the takeoff rows; re-running is a no-op; a hand-edited qty skips with
the right reason. Fixtures are synthetic; a local-only regression against the
real project files runs when they exist (guarded like the plansheet Pioneer
tests — no literal user paths).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec.apply import (
    apply_takeoff, build_geometry, element_to_line, render_apply_report)
from estimating_tools.estimate_spec.build import generate
from estimating_tools.estimate_spec.cli import main as cli_main
from estimating_tools.estimate_spec.format_pack import ENGINE_DIR, load_pack
from estimating_tools.estimate_spec.scaffold import scaffold_spec, validate_spec
from estimating_tools.takeoff.model import CanonicalTakeoff, TakeoffRow
from estimating_tools.estimate_spec.tests.test_scaffold import (
    sample_bridge_manifest, sample_bridge_structures)

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_DIR = ENGINE_DIR / "tests" / "fixtures" / "packs" / "legacy_demo"
ALT_DIR = FIXTURES / "packs" / "alt"


@pytest.fixture(scope="module")
def demo_pack():
    return load_pack(LEGACY_DIR)


@pytest.fixture(scope="module")
def alt_pack():
    return load_pack(ALT_DIR)


def sample_bridge_takeoff() -> CanonicalTakeoff:
    return CanonicalTakeoff.from_json(
        (FIXTURES / "sample_bridge_takeoff.json").read_text(encoding="utf-8"))


def sample_bridge_spec(pack=None) -> dict:
    return scaffold_spec(sample_bridge_manifest(), sample_bridge_structures(),
                         generated_at="2026-08-02T00:00:00+00:00", pack=pack).spec


# ---------------------------------------------------------------------------
# element -> geometry line routing
# ---------------------------------------------------------------------------

def test_footing_routes_to_ftg_cy(alt_pack):
    line, note = element_to_line({"name": "F1", "section_type": "footing",
                                  "count": 1, "length_ft": 32.0, "width_ft": 5.0,
                                  "height_ft": 2.5}, alt_pack)
    assert note is None
    assert line["ftg_cy"] == pytest.approx(400 / 27, abs=1e-4)
    assert line["ftg_cf"] == pytest.approx(400.0)
    assert line["wall_cy"] == 0
    assert line["length"] == 32.0 and line["height"] == 2.5


def test_walls_and_wing_wall_route_to_wall_cy(alt_pack):
    for stype in ("walls", "wing_wall"):
        line, note = element_to_line({"name": "W", "section_type": stype,
                                      "count": 1, "length_ft": 10.0,
                                      "width_ft": 1.0, "height_ft": 8.0}, alt_pack)
        assert note is None
        assert line["wall_cy"] == pytest.approx(80 / 27, abs=1e-4)
        assert line["ftg_cy"] == 0


def test_deck_rides_wall_cy_with_span_prefix(alt_pack):
    # "SPAN" is the alt pack's own label_prefix for `decks` (see
    # seed.yaml's takeoff_mapping) — distinct from the reference pack's "DECK".
    line, note = element_to_line({"name": "S-DECK-1", "section_type": "decks",
                                  "count": 1, "length_ft": 45.0, "width_ft": 30.0,
                                  "height_ft": 1.5}, alt_pack)
    assert note is None
    assert line["label"] == "SPAN S-DECK-1"
    assert line["wall_cy"] == pytest.approx(45 * 30 * 1.5 / 27, abs=1e-3)


def test_count_multiplies_cy_and_labels(alt_pack):
    line, _ = element_to_line({"name": "WING", "section_type": "wing_wall",
                               "count": 2, "length_ft": 22.75, "width_ft": 1.0,
                               "height_ft": 8.0}, alt_pack)
    assert line["label"] == "WING x2"
    assert line["wall_cy"] == pytest.approx(2 * 22.75 * 8 / 27, abs=1e-4)


def test_incomplete_dimensions_become_labeled_zero_line_with_note(alt_pack):
    line, note = element_to_line({"name": "S-DECK-1", "section_type": "decks",
                                  "count": 1, "length_ft": None, "width_ft": 1.5,
                                  "height_ft": None}, alt_pack)
    assert line["label"] == "SPAN S-DECK-1"
    assert line["wall_cy"] == 0 and line["ftg_cy"] == 0
    assert "missing length/height" in note


def test_unrouted_section_type_is_visible_not_silent(alt_pack):
    line, note = element_to_line({"name": "R1", "section_type": "railing",
                                  "count": 1, "length_ft": 69.5, "width_ft": 0.5,
                                  "height_ft": 2.0}, alt_pack)
    assert line["wall_cy"] == 0 and line["ftg_cy"] == 0
    assert "no CY column" in note


def test_build_geometry_collects_notes(alt_pack):
    block, notes = build_geometry([
        {"name": "F1", "section_type": "footing", "count": 1,
         "length_ft": 27.0, "width_ft": 1.0, "height_ft": 1.0},
        {"name": "??", "section_type": "footing", "count": 1,
         "length_ft": None, "width_ft": None, "height_ft": None}], alt_pack)
    assert block["kind"] == "geometry" and len(block["lines"]) == 2
    assert len(notes) == 1 and notes[0].startswith("apply-takeoff:")


# ---------------------------------------------------------------------------
# sample-bridge end-to-end — the exit-criterion numbers
# ---------------------------------------------------------------------------

def _apply_sample_bridge(pack):
    return apply_takeoff(sample_bridge_spec(pack), sample_bridge_takeoff(), pack=pack, today="2026-08-02")


def test_sample_bridge_quantities_land_on_the_three_items(alt_pack):
    result = _apply_sample_bridge(alt_pack)
    by_no = {it["item_no"]: it for it in result.spec["items"]}
    assert by_no["2217-40"]["qty"] == 75.00      # deck
    assert by_no["2217-38"]["qty"] == 29.63      # footing
    assert by_no["2217-39"]["qty"] == 104.44     # stems + wings
    assert len(result.matched) == 3
    validate_spec(result.spec, pack=alt_pack)


def test_sample_bridge_geometry_cy_sums_match_the_takeoff_rows(alt_pack):
    result = _apply_sample_bridge(alt_pack)
    by_no = {it["item_no"]: it for it in result.spec["items"]}
    ftg_lines = by_no["2217-38"]["takeoff"]["lines"]
    assert sum(l["ftg_cy"] for l in ftg_lines) == pytest.approx(29.6296, abs=1e-3)
    wall_lines = by_no["2217-39"]["takeoff"]["lines"]
    assert sum(l["wall_cy"] for l in wall_lines) == pytest.approx(104.4437, abs=1e-3)
    assert all(l["ftg_cy"] == 0 for l in wall_lines)


def test_sample_bridge_deck_without_dims_is_zero_line_plus_note(alt_pack):
    result = _apply_sample_bridge(alt_pack)
    deck = next(it for it in result.spec["items"] if it["item_no"] == "2217-40")
    (line,) = deck["takeoff"]["lines"]
    assert line["label"] == "SPAN S-DECK-1"
    assert line["wall_cy"] == 0
    assert any("missing" in n for n in deck["notes"])
    assert any(n == "qty 75.00 from takeoff sample-bridge 2026-08-02"
               for n in deck["notes"])


def test_sample_bridge_unmatched_both_directions_and_advisory_deltas(alt_pack):
    result = _apply_sample_bridge(alt_pack)
    # rows for items outside the structures selection can't match
    unmatched_numbers = {r["item_number"] for r in result.unmatched_rows}
    assert unmatched_numbers == {"2217-36", "2217-61", "2217-66"}
    assert result.unmatched_items == []          # every selected standard item hit
    report = render_apply_report(result)
    assert "Official vs measured" in report
    assert "104.44" in report and "100" in report    # measured vs official qty
    assert "no spec item matches" in report


def test_sample_bridge_rerun_is_a_noop(alt_pack):
    first = _apply_sample_bridge(alt_pack)
    second = apply_takeoff(first.spec, sample_bridge_takeoff(), pack=alt_pack, today="2026-08-03")
    assert second.matched == []
    assert len(second.unchanged) == 3
    assert second.spec == first.spec             # no new notes, no churn


def test_sample_bridge_hand_edited_qty_skips_with_reason_then_force_applies(alt_pack):
    spec = sample_bridge_spec(alt_pack)
    ftg = next(it for it in spec["items"] if it["item_no"] == "2217-38")
    ftg["qty"] = 33.0                            # estimator's hand edit
    result = apply_takeoff(spec, sample_bridge_takeoff(), pack=alt_pack, today="2026-08-02")
    assert len(result.matched) == 2
    (skip,) = result.skipped
    assert skip["item_no"] == "2217-38"
    assert "hand-edited" in skip["reason"]
    forced = apply_takeoff(spec, sample_bridge_takeoff(), pack=alt_pack, force=True, today="2026-08-02")
    by_no = {it["item_no"]: it for it in forced.spec["items"]}
    assert by_no["2217-38"]["qty"] == 29.63


def test_hand_authored_spec_without_meta_is_skipped(alt_pack):
    spec = sample_bridge_spec(alt_pack)
    for it in spec["items"]:
        it.pop("scaffold_meta", None)
    result = apply_takeoff(spec, sample_bridge_takeoff(), pack=alt_pack)
    assert result.matched == []
    assert all("hand-authored" in s["reason"] for s in result.skipped)


def test_applied_spec_builds_to_a_workbook(alt_pack):
    result = _apply_sample_bridge(alt_pack)
    wb = generate(result.spec, alt_pack)
    assert "38c0366 2217-39" in wb.sheetnames


def test_cost_code_secondary_match(alt_pack):
    spec = sample_bridge_spec(alt_pack)
    takeoff = CanonicalTakeoff(organization_id=0, project_ref="x", rows=[])
    from estimating_tools.takeoff.model import TakeoffRow
    takeoff.rows.append(TakeoffRow(
        description="Footing by code", kind="quantity", quantity=29.63, unit="CY",
        cost_code="FTG-CONC", schedule="Base Bid"))
    result = apply_takeoff(spec, takeoff, pack=alt_pack, today="2026-08-02")
    assert [m["item_no"] for m in result.matched] == ["2217-38"]


def test_same_item_number_in_two_schedules_matches_exactly(alt_pack):
    """PR #74 review: a row must land on the item in ITS schedule, and a
    schedule-less (hand-authored) item must not steal from an exact match."""
    from estimating_tools.takeoff.model import TakeoffRow
    spec = sample_bridge_spec(alt_pack)
    ftg = next(it for it in spec["items"] if it["item_no"] == "2217-38")
    # a hand-authored twin with no scaffold_meta, listed FIRST
    twin = json.loads(json.dumps({k: v for k, v in ftg.items()
                                  if k != "scaffold_meta"}))
    twin["sheet"] = "ALT 2217-38"
    spec["items"].insert(0, twin)
    # and a scaffolded twin in another schedule
    twin2 = json.loads(json.dumps(ftg))
    twin2["sheet"] = "ALT2 2217-38"
    twin2["scaffold_meta"]["schedule"] = "Additive Alt 1"
    spec["items"].append(twin2)

    takeoff = CanonicalTakeoff(organization_id=0, project_ref="x", rows=[
        TakeoffRow(description="ftg", kind="quantity", quantity=29.6296,
                   unit="CY", item_number="2217-38", schedule="Base Bid")])
    result = apply_takeoff(spec, takeoff, pack=alt_pack, today="2026-08-02")
    assert len(result.matched) == 1
    applied = [it for it in result.spec["items"]
               if it["item_no"] == "2217-38" and it.get("qty") == 29.63]
    assert len(applied) == 1
    assert applied[0]["sheet"] == "38c0366 2217-38"     # not the hand twin
    assert applied[0]["scaffold_meta"]["schedule"] == "Base Bid"


def test_schedule_less_fallback_only_when_no_exact_candidate(alt_pack):
    from estimating_tools.takeoff.model import TakeoffRow
    spec = sample_bridge_spec(alt_pack)
    ftg = next(it for it in spec["items"] if it["item_no"] == "2217-38")
    ftg["scaffold_meta"]["schedule"] = "Some Other Schedule"
    takeoff = CanonicalTakeoff(organization_id=0, project_ref="x", rows=[
        TakeoffRow(description="ftg", kind="quantity", quantity=29.6296,
                   unit="CY", item_number="2217-38", schedule="Base Bid")])
    # wrong schedule, no schedule-less candidate -> stays unmatched (visible)
    result = apply_takeoff(spec, takeoff, pack=alt_pack, today="2026-08-02")
    assert result.matched == []
    assert result.unmatched_rows[0]["item_number"] == "2217-38"


def test_material_rows_are_reported_not_dropped(alt_pack):
    from estimating_tools.takeoff.model import TakeoffRow
    takeoff = CanonicalTakeoff(organization_id=0, rows=[TakeoffRow(
        description="Rebar", kind="material", quantity=1, assembly_ref="a")])
    result = apply_takeoff(sample_bridge_spec(alt_pack), takeoff, pack=alt_pack)
    assert result.unmatched_rows[0]["reason"] == "unsupported row kind 'material'"


# ---------------------------------------------------------------------------
# pack-driven takeoff mapping (Plan C Task 5)
# ---------------------------------------------------------------------------

def _demo_spec():
    return {"items": [{"item_no": "1", "qty": 0.0, "uom": "LF",
                       "recipe": "line_item"}]}


def _demo_takeoff() -> CanonicalTakeoff:
    return CanonicalTakeoff(organization_id=0, project_ref="demo", rows=[
        TakeoffRow(description="Trench", kind="quantity", quantity=100.0,
                   unit="LF", item_number="1",
                   elements=[{"name": "T1", "section_type": "trench",
                             "count": 1, "length_ft": 100.0,
                             "width_ft": 2.0, "height_ft": 6.0}])])


def test_apply_writes_pack_takeoff_kind(demo_pack):
    """The demo pack's takeoff kind is `linear` (from its vocabulary.yaml),
    structurally distinct from the reference pack's `geometry` — a
    hardcoded 'geometry' literal coming back would fail this."""
    result = apply_takeoff(_demo_spec(), _demo_takeoff(), pack=demo_pack,
                           force=True, today="2026-09-23")
    kinds = {it["takeoff"]["kind"] for it in result.spec["items"] if "takeoff" in it}
    assert kinds == {"linear"}
    lines = result.spec["items"][0]["takeoff"]["lines"]
    assert lines[0]["trench_cy"] == pytest.approx(100 * 2 * 6 / 27, abs=1e-4)


def test_apply_does_not_add_takeoff_to_pack_rate_host_item(demo_pack):
    """The demo pack's rate-host recipe is `setup`, not the reference pack's
    `mob_item` — a hardcoded 'mob_item' comparison coming back would let a
    geometry takeoff land on the rate-host item."""
    spec = {"items": [{"item_no": "SETUP", "qty": 0.0, "uom": "LS",
                       "recipe": "setup"}]}
    takeoff = CanonicalTakeoff(organization_id=0, rows=[TakeoffRow(
        description="Setup", kind="quantity", quantity=1.0, unit="LS",
        item_number="SETUP",
        elements=[{"name": "x", "section_type": "trench", "count": 1,
                  "length_ft": 1, "width_ft": 1, "height_ft": 1}])])
    result = apply_takeoff(spec, takeoff, pack=demo_pack, force=True,
                           today="2026-09-23")
    (item,) = result.spec["items"]
    assert item["qty"] == 1.0
    assert "takeoff" not in item


def test_apply_excludes_pack_rate_host_from_unmatched_items(demo_pack):
    spec = {"items": [{"item_no": "SETUP", "qty": 1.0, "uom": "LS",
                       "recipe": "setup"}]}
    takeoff = CanonicalTakeoff(organization_id=0, rows=[])
    result = apply_takeoff(spec, takeoff, pack=demo_pack)
    assert result.unmatched_items == []


# ---------------------------------------------------------------------------
# CLI round-trip
# ---------------------------------------------------------------------------

def test_cli_apply_takeoff_writes_spec_and_report(tmp_path, alt_pack):
    spec_path = tmp_path / "sample-bridge.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(sample_bridge_spec(alt_pack), sort_keys=False),
                         encoding="utf-8")
    report_path = tmp_path / "apply-report.md"
    rc = cli_main(["apply-takeoff", str(spec_path),
                   "--takeoff", str(FIXTURES / "sample_bridge_takeoff.json"),
                   "--format", str(ALT_DIR),
                   "--report", str(report_path)])
    assert rc == 0
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    by_no = {it["item_no"]: it for it in spec["items"]}
    assert by_no["2217-39"]["qty"] == 104.44
    assert "old_qty" in report_path.read_text(encoding="utf-8")

    # idempotent re-run: no rewrite, still exit 0
    before = spec_path.read_text(encoding="utf-8")
    assert cli_main(["apply-takeoff", str(spec_path),
                     "--takeoff", str(FIXTURES / "sample_bridge_takeoff.json"),
                     "--format", str(ALT_DIR)]) == 0
    assert spec_path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# local-only regression against the real sample-bridge files (guarded; never in CI)
# ---------------------------------------------------------------------------

def _real_takeoff() -> Path:
    # No implicit default: this plugin test must not assume the layout of a
    # consumer's private repo. Opt in explicitly by setting EST_SAMPLE_BRIDGE_TAKEOFF
    # to the real sample-bridge takeoff export; unset (the common case, including
    # CI), the regression below is skipped, loudly, with the reason stated.
    env = os.environ.get("EST_SAMPLE_BRIDGE_TAKEOFF")
    return Path(env) if env else Path("/nonexistent/EST_SAMPLE_BRIDGE_TAKEOFF-not-set")


sample_bridge_local = pytest.mark.skipif(
    not _real_takeoff().is_file(),
    reason="real sample-bridge takeoff not present (local-only regression; "
           "set EST_SAMPLE_BRIDGE_TAKEOFF)")


@sample_bridge_local
def test_real_sample_bridge_takeoff_matches_the_synthetic_numbers(alt_pack):
    takeoff = CanonicalTakeoff.from_json(_real_takeoff().read_text(encoding="utf-8"))
    result = apply_takeoff(sample_bridge_spec(alt_pack), takeoff, pack=alt_pack, today="2026-08-02")
    by_no = {it["item_no"]: it for it in result.spec["items"]}
    assert by_no["2217-40"]["qty"] == 75.00
    assert by_no["2217-38"]["qty"] == 29.63
    assert by_no["2217-39"]["qty"] == 104.44
    assert sum(l["ftg_cy"] for l in by_no["2217-38"]["takeoff"]["lines"]) \
        == pytest.approx(29.6296, abs=1e-3)
    assert sum(l["wall_cy"] for l in by_no["2217-39"]["takeoff"]["lines"]) \
        == pytest.approx(104.4437, abs=1e-3)
    generate(result.spec, alt_pack)


# ---------------------------------------------------------------------------
# issue #106 addendum: two takeoff rows sharing (schedule, item_number) must
# never silently clobber one spec item (last-wins qty overwrite)
# ---------------------------------------------------------------------------

def test_second_row_matching_same_item_flags_instead_of_clobbering(demo_pack):
    spec = {"items": [{"item_no": "129", "qty": 0.0, "unit": "LF",
                       "recipe": "flat_item"}]}
    takeoff = CanonicalTakeoff(organization_id=1, project_ref="B1", rows=[])
    from estimating_tools.takeoff.model import TakeoffRow
    takeoff.rows = [
        TakeoffRow(description="Furnish pile", kind="quantity", quantity=41.0,
                   unit="LF", cost_code="PILE-200W-FRN", item_number="129"),
        TakeoffRow(description="Drive pile", kind="quantity", quantity=1.0,
                   unit="EA", cost_code="PILE-200W-DRV", item_number="129"),
    ]
    result = apply_takeoff(spec, takeoff, force=True, pack=demo_pack)
    (item,) = result.spec["items"]
    assert item["qty"] == 41.0                       # first row applied…
    clashes = [r for r in result.unmatched_rows
               if "already" in r.get("reason", "")]
    assert len(clashes) == 1                         # …second flagged, loudly
    assert clashes[0]["item_number"] == "129"
    assert clashes[0]["quantity"] == 1.0


def test_apply_lists_a_fieldbook_lump_sum_bid_item_as_unmatched():
    """fieldbook's rate_host_recipe is `lump_sum`, also the recipe of its real
    lump-sum bid items: one no takeoff row matched is reported as unmatched;
    only the scaffold-injected rate host is left out."""
    pack = load_pack(ENGINE_DIR / "packs" / "fieldbook")
    spec = {"items": [
        {"item_no": "RATES", "qty": 0, "uom": "LS", "recipe": "lump_sum",
         "description": "Rate table host (no mobilization item selected)",
         "scaffold_meta": {"source": "scaffold:rate_host"}},
        {"item_no": "1", "qty": 1, "uom": "LS", "recipe": "lump_sum",
         "description": "Mobilization"}]}
    result = apply_takeoff(spec, CanonicalTakeoff(organization_id=0, rows=[]), pack=pack)
    assert result.unmatched_items == [{"item_no": "1", "description": "Mobilization"}]
