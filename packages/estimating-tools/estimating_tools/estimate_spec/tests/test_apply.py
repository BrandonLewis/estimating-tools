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


def test_bundled_pack_routes_earthwork_to_other_cy():
    """The shipped fieldbook pack routed only footing / wall / deck, so an
    earthwork element (the whole of a roadway-excavation item) wrote a line
    with length and height and 0 CY, and the sheet summed to 0 against the
    bid quantity. Earthwork, rock and other CY bodies land in other_cy."""
    for stype in ("earthworkselement", "earthworksfill", "covering", "course"):
        line, note = element_to_line({"name": f"X {stype}", "section_type": stype,
                                      "count": 1, "length_ft": 36.44, "width_ft": 5.3718,
                                      "height_ft": 0.5486})
        assert note is None, (stype, note)
        assert line["other_cy"] == pytest.approx(36.44 * 5.3718 * 0.5486 / 27, abs=1e-3)
        assert line["footing_cy"] == 0 and line["wall_cy"] == 0 and line["deck_cy"] == 0


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


# ---------------------------------------------------------------------------
# issue #376: takeoffs applied in sequence (one per structure model) merge
# into an item they share instead of the last one replacing the others
# ---------------------------------------------------------------------------

WALL_ITEM = "2217-39"


def _wall_takeoff(walls, *, ref="demo", qty=None, **kwargs) -> CanonicalTakeoff:
    """One quantity row on the wall item; each wall is (name, global_id,
    length) with width 1 ft and height 27 ft, so its CY equals its length."""
    elements = [{"name": name, "global_id": gid, "section_type": "walls",
                 "count": 1, "length_ft": length, "width_ft": 1.0,
                 "height_ft": 27.0} for name, gid, length in walls]
    quantity = qty if qty is not None else float(sum(w[2] for w in walls))
    return CanonicalTakeoff(organization_id=0, project_ref=ref, rows=[TakeoffRow(
        description="walls", kind="quantity", quantity=quantity, unit="CY",
        item_number=WALL_ITEM, schedule="Base Bid", elements=elements)],
        **kwargs)


# two structure models that share the item; the same project_ref on both, so
# a takeoff's identity cannot be its project_ref
TAKEOFF_A = [("A-W1", "gidA1", 10.0), ("A-W2", "gidA2", 20.0)]
TAKEOFF_B = [("B-W1", "gidB1", 5.0)]


def _wall(spec) -> dict:
    return next(it for it in spec["items"] if it["item_no"] == WALL_ITEM)


def _labels(spec) -> list:
    return [line["label"] for line in _wall(spec)["takeoff"]["lines"]]


def _apply_a_then_b(alt_pack):
    first = apply_takeoff(sample_bridge_spec(alt_pack), _wall_takeoff(TAKEOFF_A),
                          pack=alt_pack, source_name="bridge", today="2026-11-05")
    second = apply_takeoff(first.spec, _wall_takeoff(TAKEOFF_B), pack=alt_pack,
                           source_name="approach slabs", today="2026-11-05")
    return first, second


def test_two_takeoffs_sharing_an_item_merge_lines_and_sum_qty(alt_pack):
    _, second = _apply_a_then_b(alt_pack)
    assert _wall(second.spec)["qty"] == 35.0
    assert _labels(second.spec) == ["A-W1", "A-W2", "B-W1"]
    assert sum(l["wall_cy"] for l in _wall(second.spec)["takeoff"]["lines"]) \
        == pytest.approx(35.0, abs=1e-3)
    assert second.merged == [{"item_no": WALL_ITEM, "schedule": "Base Bid",
                              "takeoffs": ["bridge", "approach slabs"]}]
    assert second.warnings == []
    report = render_apply_report(second)
    assert "item 2217-39: 2 takeoffs contributed (bridge, approach slabs)" in report
    validate_spec(second.spec, pack=alt_pack)


def test_reapplying_a_takeoff_replaces_only_its_own_lines(alt_pack):
    _, second = _apply_a_then_b(alt_pack)
    # takeoff A re-measured: one wall longer, one wall added
    edited = [("A-W1", "gidA1", 12.0), ("A-W2", "gidA2", 20.0),
              ("A-W3", "gidA3", 3.0)]
    third = apply_takeoff(second.spec, _wall_takeoff(edited), pack=alt_pack,
                          source_name="bridge", today="2026-11-06")
    assert _wall(third.spec)["qty"] == 40.0          # 35 (A) + 5 (B)
    assert _labels(third.spec) == ["A-W1", "A-W2", "A-W3", "B-W1"]
    assert third.warnings == []
    # and the same takeoff again is a no-op
    fourth = apply_takeoff(third.spec, _wall_takeoff(TAKEOFF_B), pack=alt_pack,
                           source_name="approach slabs", today="2026-11-07")
    assert fourth.matched == []
    assert fourth.spec == third.spec


def test_takeoff_source_id_is_its_identity_when_present(alt_pack):
    """Quantity-only rows carry no element GlobalIds; the takeoff's own
    `source_id` tells two of them apart (same project_ref on both)."""
    def qty_only(source_id, quantity):
        return CanonicalTakeoff(organization_id=0, project_ref="demo",
                                source_id=source_id, rows=[TakeoffRow(
                                    description="walls", kind="quantity",
                                    quantity=quantity, unit="CY",
                                    item_number=WALL_ITEM, schedule="Base Bid")])
    spec = sample_bridge_spec(alt_pack)
    spec = apply_takeoff(spec, qty_only("bridge-model", 50.0), pack=alt_pack).spec
    spec = apply_takeoff(spec, qty_only("slab-model", 6.0), pack=alt_pack).spec
    assert _wall(spec)["qty"] == 56.0
    again = apply_takeoff(spec, qty_only("bridge-model", 53.0), pack=alt_pack)
    assert _wall(again.spec)["qty"] == 59.0
    assert again.merged[0]["takeoffs"] == ["bridge-model", "slab-model"]


def test_takeoff_source_id_round_trips_through_json():
    text = json.dumps({"organization_id": 0, "project_ref": "demo",
                       "source_id": "bridge-model", "rows": []})
    assert CanonicalTakeoff.from_json(text).source_id == "bridge-model"
    assert CanonicalTakeoff.from_json(
        json.dumps({"organization_id": 0, "rows": []})).source_id is None


def _old_spec_applied_by_a(alt_pack) -> dict:
    """A spec written by apply-takeoff before #376: the lines and the
    provenance note are there, but nothing records which takeoff owns them."""
    spec = apply_takeoff(sample_bridge_spec(alt_pack), _wall_takeoff(TAKEOFF_A),
                         pack=alt_pack, today="2026-11-05").spec
    _wall(spec)["scaffold_meta"].pop("takeoffs", None)
    return spec


def test_old_spec_lines_from_another_takeoff_are_refused(alt_pack):
    """An older spec cannot say which takeoff wrote its lines: summing could
    double count and replacing could drop a structure, so a takeoff that
    did not write them is refused (item unchanged) until --replace."""
    spec = _old_spec_applied_by_a(alt_pack)
    result = apply_takeoff(spec, _wall_takeoff(TAKEOFF_B), pack=alt_pack,
                           source_name="approach slabs", today="2026-11-05")
    assert _wall(result.spec) == _wall(spec)
    (refused,) = result.refused
    assert "predate takeoff ownership" in refused["reason"]
    assert "--adopt-legacy" in refused["reason"]
    assert "predate takeoff ownership" in render_apply_report(result)
    replaced = apply_takeoff(spec, _wall_takeoff(TAKEOFF_B), pack=alt_pack,
                             source_name="approach slabs", replace=True)
    assert _wall(replaced.spec)["qty"] == 5.0
    assert _labels(replaced.spec) == ["B-W1"]
    validate_spec(replaced.spec, pack=alt_pack)


def test_old_spec_rerun_of_the_takeoff_that_wrote_it_takes_ownership(alt_pack):
    """The same lines again: that takeoff wrote them. It takes ownership
    (no sum, no warning) and later takeoffs merge as usual."""
    spec = _old_spec_applied_by_a(alt_pack)
    again = apply_takeoff(spec, _wall_takeoff(TAKEOFF_A), pack=alt_pack,
                          source_name="bridge", today="2026-11-06")
    assert _wall(again.spec)["qty"] == 30.0
    assert _labels(again.spec) == ["A-W1", "A-W2"]
    assert again.warnings == [] and again.refused == []
    assert [c["source"] for c in _wall(again.spec)["scaffold_meta"]["takeoffs"]] \
        == ["bridge"]
    merged = apply_takeoff(again.spec, _wall_takeoff(TAKEOFF_B), pack=alt_pack,
                           source_name="approach slabs")
    assert _wall(merged.spec)["qty"] == 35.0


def test_replace_drops_other_takeoffs_lines_and_warns(alt_pack):
    _, second = _apply_a_then_b(alt_pack)
    replaced = apply_takeoff(second.spec, _wall_takeoff(TAKEOFF_A), pack=alt_pack,
                             source_name="bridge", replace=True)
    assert _wall(replaced.spec)["qty"] == 30.0
    assert _labels(replaced.spec) == ["A-W1", "A-W2"]
    (warning,) = replaced.warnings
    assert "approach slabs" in warning and "replaced" in warning


def test_cli_sequential_applies_merge_and_report_names_the_takeoffs(tmp_path, alt_pack):
    spec_path = tmp_path / "demo.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(sample_bridge_spec(alt_pack), sort_keys=False),
                         encoding="utf-8")

    def dump(name, walls):
        rows = [vars(r) for r in _wall_takeoff(walls).rows]
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"organization_id": 0, "project_ref": "demo",
                                    "rows": rows}), encoding="utf-8")
        return str(path)

    bridge, slabs = dump("bridge", TAKEOFF_A), dump("slabs", TAKEOFF_B)
    report_path = tmp_path / "apply-report.md"
    for takeoff in (bridge, slabs):
        assert cli_main(["apply-takeoff", str(spec_path), "--takeoff", takeoff,
                         "--format", str(ALT_DIR), "--force",
                         "--report", str(report_path)]) == 0
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    assert _wall(spec)["qty"] == 35.0
    assert _labels(spec) == ["A-W1", "A-W2", "B-W1"]
    assert ("item 2217-39: 2 takeoffs contributed (bridge, slabs)"
            in report_path.read_text(encoding="utf-8"))


def test_scaffold_merge_resets_ownership_with_the_geometry(alt_pack):
    """scaffold --merge puts the official qty and placeholder geometry back
    on an applied item; no takeoff owns anything then, so re-applying one
    takeoff gives its own quantity, not official + measured."""
    from estimating_tools.estimate_spec.scaffold import merge_scaffold
    _, second = _apply_a_then_b(alt_pack)
    merged, _ = merge_scaffold(second.spec, sample_bridge_spec(alt_pack))
    assert _wall(merged)["scaffold_meta"]["takeoffs"] == []
    again = apply_takeoff(merged, _wall_takeoff(TAKEOFF_A), pack=alt_pack,
                          source_name="bridge")
    assert _wall(again.spec)["qty"] == 30.0
    assert _labels(again.spec) == ["A-W1", "A-W2"]
    assert again.warnings == []


def test_scaffold_merge_keeps_ownership_when_it_keeps_the_lines(alt_pack):
    from estimating_tools.estimate_spec.scaffold import merge_scaffold
    _, second = _apply_a_then_b(alt_pack)
    wall = _wall(second.spec)
    record = wall["scaffold_meta"]["takeoffs"]
    wall["qty"] = 36.0                                   # hand edits: merge
    wall["takeoff"]["lines"][0]["label"] = "A-W1 (checked)"   # leaves both
    merged, _ = merge_scaffold(second.spec, sample_bridge_spec(alt_pack))
    assert _wall(merged)["scaffold_meta"]["takeoffs"] == record


# ---------------------------------------------------------------------------
# PR #441 review: identity is source_id, else the takeoff file's name; never
# element GlobalIds or project_ref. Each reviewer case is a regression test.
# ---------------------------------------------------------------------------

def _apply(spec, takeoff, alt_pack, name=None, **kwargs):
    return apply_takeoff(spec, takeoff, pack=alt_pack, source_name=name, **kwargs)


def _qty_only(quantity, unit="CY", **kwargs) -> CanonicalTakeoff:
    return CanonicalTakeoff(organization_id=0, project_ref="demo", rows=[TakeoffRow(
        description="walls", kind="quantity", quantity=quantity, unit=unit,
        item_number=WALL_ITEM, schedule="Base Bid")], **kwargs)


def test_review_case1_structures_sharing_a_global_id_both_count_and_warn(alt_pack):
    """Per-structure models of one project derive GlobalIds from one
    namespace, so a same-named element in two of them shares its id: two
    takeoffs, not one (was 15, silently)."""
    a = _wall_takeoff([("Abut", "G-shared", 10.0), ("A-W2", "gidA2", 20.0)])
    b = _wall_takeoff([("Abut", "G-shared", 10.0), ("B-W1", "gidB1", 5.0)])
    spec = _apply(sample_bridge_spec(alt_pack), a, alt_pack, "east-slab").spec
    second = _apply(spec, b, alt_pack, "west-slab")
    assert _wall(second.spec)["qty"] == 45.0
    (warning,) = second.warnings
    assert "possible double count" in warning
    assert "west-slab" in warning and "east-slab" in warning


def _bridge_and_slab(alt_pack) -> dict:
    spec = _apply(sample_bridge_spec(alt_pack),
                  _wall_takeoff([("A-W1", "gidA1", 10.0)]), alt_pack, "bridge").spec
    return _apply(spec, _wall_takeoff([("B-W1", "gidB1", 5.0)]), alt_pack, "slab").spec


def test_review_case2_federated_after_per_structure_adds_and_warns(alt_pack):
    """A federated model re-namespaces GlobalIds and its takeoff JSON has no
    federation marker, so it cannot replace the per-structure takeoffs: it
    adds, and the element names (all of each per-structure takeoff's names
    appear in it) raise the double-count warning; the report says not to
    mix them."""
    federated = _wall_takeoff([("A-W1", "fedA1", 10.0), ("B-W1", "fedB1", 5.0)])
    result = _apply(_bridge_and_slab(alt_pack), federated, alt_pack, "federated")
    assert _wall(result.spec)["qty"] == 30.0
    assert len(result.warnings) == 2
    assert all("possible double count" in w and "federated" in w
               for w in result.warnings)
    assert "must not both be applied" in render_apply_report(result)


def test_review_case2b_federated_sharing_global_ids_adds_and_warns(alt_pack):
    federated = _wall_takeoff([("A-W1", "gidA1", 10.0), ("B-W1", "gidB1", 5.0)])
    result = _apply(_bridge_and_slab(alt_pack), federated, alt_pack, "federated")
    assert _wall(result.spec)["qty"] == 30.0
    assert len(result.warnings) == 2
    assert all("shared element GlobalId" in w for w in result.warnings)


def test_review_case2c_per_structure_reapplied_after_federated(alt_pack):
    federated = _wall_takeoff([("A-W1", "gidA1", 10.0), ("B-W1", "gidB1", 5.0)])
    spec = _apply(_bridge_and_slab(alt_pack), federated, alt_pack, "federated").spec
    again = _apply(spec, _wall_takeoff([("A-W1", "gidA1", 12.0)]), alt_pack, "bridge")
    assert _wall(again.spec)["qty"] == 32.0          # 12 + 5 + 15: nothing dropped
    assert any("possible double count" in w and "federated" in w
               for w in again.warnings)


def test_review_case3_same_file_with_regenerated_global_ids_replaces(alt_pack):
    spec = _apply(sample_bridge_spec(alt_pack),
                  _wall_takeoff([("A-W1", "x1", 10.0)]), alt_pack, "bridge").spec
    again = _apply(spec, _wall_takeoff([("A-W1", "y1", 10.0)]), alt_pack, "bridge")
    assert _wall(again.spec)["qty"] == 10.0
    assert _labels(again.spec) == ["A-W1"]
    (warning,) = again.warnings
    assert "shares no element GlobalId" in warning


def test_review_case4_source_id_and_file_name_are_one_identity(alt_pack):
    spec = apply_takeoff(sample_bridge_spec(alt_pack),
                         _wall_takeoff([("A-W1", "gidA1", 10.0)], source_id="bridge"),
                         pack=alt_pack).spec
    again = _apply(spec, _wall_takeoff([("A-W1", "gidA1", 10.0)]), alt_pack, "bridge")
    assert _wall(again.spec)["qty"] == 10.0
    assert again.matched == [] and again.warnings == []


def test_review_case5_old_spec_other_takeoff_with_equal_qty_is_refused(alt_pack):
    """Quantity-only rows write no lines to compare, so an older spec's
    owner cannot be recognised: refused, never summed or dropped."""
    spec = _apply(sample_bridge_spec(alt_pack), _qty_only(30.0), alt_pack).spec
    _wall(spec)["scaffold_meta"].pop("takeoffs")
    result = _apply(spec, _qty_only(30.0), alt_pack, "other-slab")
    assert _wall(result.spec) == _wall(spec)
    assert result.matched == []
    assert "predate takeoff ownership" in result.refused[0]["reason"]


def test_review_case6_quantity_only_rows_of_one_project_add(alt_pack):
    spec = _apply(sample_bridge_spec(alt_pack), _qty_only(30.0), alt_pack, "bridge").spec
    result = _apply(spec, _qty_only(5.0), alt_pack, "slab")
    assert _wall(result.spec)["qty"] == 35.0
    assert result.warnings == []


def test_review_case7_hand_added_line_keeps_everything_and_warns(alt_pack):
    spec = _apply(sample_bridge_spec(alt_pack), _wall_takeoff(TAKEOFF_A),
                  alt_pack, "bridge").spec
    spec = _apply(spec, _wall_takeoff([("B-W1", "gidB1", 5.0), ("B-W2", "gidB2", 1.0)]),
                  alt_pack, "slab").spec
    lines = _wall(spec)["takeoff"]["lines"]
    lines.append(dict(lines[0], label="HAND"))
    result = _apply(spec, _wall_takeoff([("B-W1", "gidB1", 6.0), ("B-W2", "gidB2", 1.0)]),
                    alt_pack, "slab", force=True)
    assert _wall(result.spec)["qty"] == 37.0          # 30 (bridge) + 7 (slab)
    labels = _labels(result.spec)
    assert "HAND" in labels and labels[:2] == ["A-W1", "A-W2"]
    assert any("no longer match" in w for w in result.warnings)


def test_review_case8_a_different_unit_is_refused(alt_pack):
    spec = _apply(sample_bridge_spec(alt_pack),
                  _wall_takeoff([("A-W1", "gidA1", 10.0)]), alt_pack, "bridge").spec
    cf = _wall_takeoff([("B-W1", "gidB1", 5.0)])
    cf.rows[0].unit, cf.rows[0].quantity = "CF", 135.0
    result = _apply(spec, cf, alt_pack, "slab")
    assert _wall(result.spec) == _wall(spec)          # left as it was
    (refused,) = result.refused
    assert refused["item_no"] == WALL_ITEM and "CF" in refused["reason"]
    assert "Refused" in render_apply_report(result)


def test_unit_differing_from_other_takeoffs_is_refused(alt_pack):
    """The item has no uom to check against: the contributors' units are."""
    spec = sample_bridge_spec(alt_pack)
    _wall(spec).pop("uom")
    spec = _apply(spec, _qty_only(10.0), alt_pack, "bridge").spec
    result = _apply(spec, _qty_only(270.0, unit="CF"), alt_pack, "slab")
    assert _wall(result.spec)["qty"] == 10.0
    assert "other takeoffs" in result.refused[0]["reason"]


def test_unit_aliases_are_the_same_unit(alt_pack):
    result = _apply(sample_bridge_spec(alt_pack), _qty_only(10.0, unit="CUYD"),
                    alt_pack, "bridge")
    assert result.refused == [] and _wall(result.spec)["qty"] == 10.0


def test_empty_record_is_owned_by_no_takeoff(alt_pack):
    """`takeoffs: []` (scaffold --merge) behaves like an untouched item: the
    takeoff's lines replace the scaffold geometry; no earlier-takeoff
    contributor, no warning."""
    spec = sample_bridge_spec(alt_pack)
    _wall(spec)["scaffold_meta"]["takeoffs"] = []
    _wall(spec)["notes"].append("qty 99.00 from takeoff old 2026-01-01")
    _wall(spec)["scaffold_meta"]["field_hashes"].pop("qty")
    result = _apply(spec, _wall_takeoff(TAKEOFF_A), alt_pack, "bridge")
    assert _wall(result.spec)["qty"] == 30.0
    assert _labels(result.spec) == ["A-W1", "A-W2"]
    assert result.warnings == []


def test_takeoff_kind_mismatch_has_its_own_warning(alt_pack):
    spec = _bridge_and_slab(alt_pack)
    _wall(spec)["takeoff"] = {"kind": "subcontractor", "lines": []}
    result = _apply(spec, _wall_takeoff([("A-W1", "gidA1", 11.0)]), alt_pack,
                    "bridge", force=True)
    assert _wall(result.spec)["qty"] == 16.0
    (warning,) = result.warnings
    assert "kind 'subcontractor'" in warning and "no longer match" not in warning


@pytest.mark.parametrize("item_uom,row_unit", [
    ("TON", "TN"), ("CY", "C.Y."), ("SF", "SQ FT"), ("LB", "POUNDS"),
    ("LF", "LIN FT"), ("LS", "LUMP SUM")])
def test_unit_spellings_are_the_same_unit(alt_pack, item_uom, row_unit):
    spec = sample_bridge_spec(alt_pack)
    _wall(spec)["uom"] = item_uom
    result = _apply(spec, _qty_only(10.0, unit=row_unit), alt_pack, "bridge",
                    force=True)
    assert result.refused == [] and _wall(result.spec)["qty"] == 10.0


def test_cwt_is_not_a_ton(alt_pack):
    spec = sample_bridge_spec(alt_pack)
    _wall(spec)["uom"] = "TON"
    result = _apply(spec, _qty_only(10.0, unit="CWT"), alt_pack, "bridge",
                    force=True)
    assert len(result.refused) == 1


def test_warnings_name_the_takeoff_identity_not_its_project_ref(alt_pack):
    spec = apply_takeoff(sample_bridge_spec(alt_pack),
                         _wall_takeoff([("A-W1", "gidA1", 10.0)], source_id="bridge"),
                         pack=alt_pack).spec
    result = apply_takeoff(spec, _wall_takeoff([("A-W1", "gidA1", 10.0)]),
                           pack=alt_pack)
    (warning,) = result.warnings
    assert "(unnamed)" in warning and "bridge" in warning
    assert "demo" not in warning


# ---------------------------------------------------------------------------
# generic takeoff file names (bridge/takeoff.json, approach/takeoff.json)
# ---------------------------------------------------------------------------

def _per_folder_takeoffs(tmp_path, alt_pack):
    spec_path = tmp_path / "demo.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(sample_bridge_spec(alt_pack), sort_keys=False),
                         encoding="utf-8")
    paths = []
    for folder, quantity in (("bridge", 30.0), ("approach", 5.0)):
        (tmp_path / folder).mkdir()
        path = tmp_path / folder / "takeoff.json"
        path.write_text(json.dumps({"organization_id": 0, "project_ref": "demo",
                                    "rows": [vars(r) for r in _qty_only(quantity).rows]}),
                        encoding="utf-8")
        paths.append(str(path))
    return spec_path, paths


def test_generic_takeoff_file_name_is_refused_with_exit_2(tmp_path, alt_pack, capsys):
    """Rebar rows carry no elements, so nothing else could tell two
    structures' takeoff.json apart: refuse rather than let one replace
    the other."""
    spec_path, paths = _per_folder_takeoffs(tmp_path, alt_pack)
    before = spec_path.read_text(encoding="utf-8")
    report = tmp_path / "apply-report.md"
    assert cli_main(["apply-takeoff", str(spec_path), "--takeoff", paths[0],
                     "--format", str(ALT_DIR), "--report", str(report)]) == 2
    assert spec_path.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "REFUSED: 1 row(s) not applied" in out
    assert "--source-id or a per-structure file name" in out
    assert "--source-id or a per-structure file name" in report.read_text(encoding="utf-8")


def test_source_id_flag_names_takeoffs_with_generic_file_names(tmp_path, alt_pack):
    spec_path, paths = _per_folder_takeoffs(tmp_path, alt_pack)
    for path, source_id in zip(paths, ("bridge", "approach")):
        assert cli_main(["apply-takeoff", str(spec_path), "--takeoff", path,
                         "--format", str(ALT_DIR), "--source-id", source_id]) == 0
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    assert _wall(spec)["qty"] == 35.0
    # and re-measuring one structure replaces only its own quantity
    assert cli_main(["apply-takeoff", str(spec_path), "--takeoff", paths[0],
                     "--format", str(ALT_DIR), "--source-id", "approach"]) == 0
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    assert _wall(spec)["qty"] == 60.0     # bridge 30 + approach now 30


def test_takeoff_source_id_in_the_json_names_a_generic_file(tmp_path, alt_pack):
    spec_path, paths = _per_folder_takeoffs(tmp_path, alt_pack)
    for path, source_id in zip(paths, ("bridge", "approach")):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["source_id"] = source_id
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        assert cli_main(["apply-takeoff", str(spec_path), "--takeoff", path,
                         "--format", str(ALT_DIR)]) == 0
    assert _wall(yaml.safe_load(spec_path.read_text(encoding="utf-8")))["qty"] == 35.0


# ---------------------------------------------------------------------------
# --adopt-legacy: take over items whose lines predate ownership without
# touching items other takeoffs already share (--replace would drop them)
# ---------------------------------------------------------------------------

FOOTING_ITEM = "2217-38"


def _bridge_takeoff(footing_ft: float, wall_ft: float) -> CanonicalTakeoff:
    """The bridge model: one footing row and one wall row (CY = length)."""
    def row(item_number, name, gid, stype, length):
        return TakeoffRow(description=name, kind="quantity", quantity=length,
                          unit="CY", item_number=item_number, schedule="Base Bid",
                          elements=[{"name": name, "global_id": gid,
                                     "section_type": stype, "count": 1,
                                     "length_ft": length, "width_ft": 1.0,
                                     "height_ft": 27.0}])
    return CanonicalTakeoff(organization_id=0, project_ref="demo", rows=[
        row(FOOTING_ITEM, "F1", "gidF1", "footing", footing_ft),
        row(WALL_ITEM, "A-W1", "gidA1", "walls", wall_ft)])


def _legacy_footing_and_merged_wall(alt_pack) -> dict:
    """Footing applied before ownership was recorded; wall merged from the
    bridge (30) and the slab (5)."""
    spec = apply_takeoff(sample_bridge_spec(alt_pack), _bridge_takeoff(20.0, 30.0),
                         pack=alt_pack, source_name="bridge").spec
    spec = apply_takeoff(spec, _wall_takeoff([("B-W1", "gidB1", 5.0)]),
                         pack=alt_pack, source_name="slab").spec
    footing = next(it for it in spec["items"] if it["item_no"] == FOOTING_ITEM)
    footing["scaffold_meta"].pop("takeoffs")
    assert _wall(spec)["qty"] == 35.0
    return spec


def _footing(spec) -> dict:
    return next(it for it in spec["items"] if it["item_no"] == FOOTING_ITEM)


def test_remeasured_takeoff_refuses_the_legacy_item_and_merges_the_rest(alt_pack):
    spec = _legacy_footing_and_merged_wall(alt_pack)
    result = apply_takeoff(spec, _bridge_takeoff(22.0, 31.0), pack=alt_pack,
                           source_name="bridge")
    assert _footing(result.spec) == _footing(spec)
    (refused,) = result.refused
    assert refused["item_no"] == FOOTING_ITEM
    assert "--adopt-legacy" in refused["reason"]
    assert "--replace" not in refused["reason"]
    assert _wall(result.spec)["qty"] == 36.0          # bridge 31 + slab 5


def test_adopt_legacy_takes_over_legacy_items_and_leaves_merged_ones_merged(alt_pack):
    spec = _legacy_footing_and_merged_wall(alt_pack)
    result = apply_takeoff(spec, _bridge_takeoff(22.0, 31.0), pack=alt_pack,
                           source_name="bridge", adopt_legacy=True)
    assert result.refused == []
    assert _footing(result.spec)["qty"] == 22.0       # replaced, not summed
    assert [ln["label"] for ln in _footing(result.spec)["takeoff"]["lines"]] == ["F1"]
    assert [c["source"] for c in _footing(result.spec)["scaffold_meta"]["takeoffs"]] \
        == ["bridge"]
    assert _wall(result.spec)["qty"] == 36.0          # slab's 5 kept
    assert _labels(result.spec) == ["A-W1", "B-W1"]
    assert not any("replaced lines it did not own" in w for w in result.warnings)
    validate_spec(result.spec, pack=alt_pack)


def test_replace_drops_other_takeoffs_on_every_matched_item(alt_pack):
    """Why the legacy refusal points at --adopt-legacy: --replace also
    replaces the merged wall item, dropping the slab's quantity."""
    spec = _legacy_footing_and_merged_wall(alt_pack)
    result = apply_takeoff(spec, _bridge_takeoff(22.0, 31.0), pack=alt_pack,
                           source_name="bridge", replace=True)
    assert _wall(result.spec)["qty"] == 31.0
    assert any("slab" in w and "replaced lines it did not own" in w
               for w in result.warnings)


def test_cli_adopt_legacy(tmp_path, alt_pack):
    spec_path = tmp_path / "demo.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(_legacy_footing_and_merged_wall(alt_pack),
                                        sort_keys=False), encoding="utf-8")
    takeoff = tmp_path / "bridge.json"
    takeoff.write_text(json.dumps({
        "organization_id": 0, "project_ref": "demo",
        "rows": [vars(r) for r in _bridge_takeoff(22.0, 31.0).rows]}), encoding="utf-8")
    args = ["apply-takeoff", str(spec_path), "--takeoff", str(takeoff),
            "--format", str(ALT_DIR)]
    assert cli_main(args) == 2                         # footing refused
    assert cli_main(args + ["--adopt-legacy"]) == 0
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    assert _footing(spec)["qty"] == 22.0
    assert _wall(spec)["qty"] == 36.0


# ---------------------------------------------------------------------------
# PR #441 Copilot review threads
# ---------------------------------------------------------------------------

def test_hand_line_after_a_and_b_then_reapplying_a_keeps_b_geometry(alt_pack):
    """Apply A and B, append a hand line, re-apply A with --force: the
    blocks no longer hash to what A and B wrote, so nothing is sliced. B's
    geometry stays (never re-labelled as the hand line) and B's qty too."""
    _, second = _apply_a_then_b(alt_pack)
    spec = second.spec
    lines = _wall(spec)["takeoff"]["lines"]
    lines.append(dict(lines[0], label="HAND"))
    result = apply_takeoff(spec, _wall_takeoff([("A-W1", "gidA1", 11.0),
                                                ("A-W2", "gidA2", 20.0)]),
                           pack=alt_pack, source_name="bridge", force=True)
    labels = _labels(result.spec)
    assert labels[:4] == ["A-W1", "A-W2", "B-W1", "HAND"]     # all kept
    assert labels.count("B-W1") == 1
    assert _wall(result.spec)["qty"] == 36.0                   # 31 + 5
    assert any("no longer match" in w for w in result.warnings)
    record = {c["source"]: c for c in _wall(result.spec)["scaffold_meta"]["takeoffs"]}
    assert record["approach slabs"]["lines"] == 0              # HAND not B's


def _two_row_model(footing_gid: str, wall_gid: str, wall_ft: float) -> CanonicalTakeoff:
    def row(item_number, name, gid, stype, length):
        return TakeoffRow(description=name, kind="quantity", quantity=length,
                          unit="CY", item_number=item_number, schedule="Base Bid",
                          elements=[{"name": name, "global_id": gid,
                                     "section_type": stype, "count": 1,
                                     "length_ft": length, "width_ft": 1.0,
                                     "height_ft": 27.0}])
    return CanonicalTakeoff(organization_id=0, project_ref="demo", rows=[
        row("2217-38", "F1", footing_gid, "footing", 20.0),
        row(WALL_ITEM, "W", wall_gid, "walls", wall_ft)])


def test_revised_model_replacing_one_element_is_one_takeoff_without_a_false_warning(alt_pack):
    """The footing keeps its GlobalId, the wall's only element is replaced
    (w1 -> w2). Identity is the file name, so the wall is replaced, not
    summed; and since the takeoff still shares GlobalIds with what it wrote
    before (the footing), no "shares no element GlobalId" warning."""
    spec = apply_takeoff(sample_bridge_spec(alt_pack), _two_row_model("f1", "w1", 30.0),
                         pack=alt_pack, source_name="bridge").spec
    result = apply_takeoff(spec, _two_row_model("f1", "w2", 32.0), pack=alt_pack,
                           source_name="bridge")
    assert _wall(result.spec)["qty"] == 32.0
    assert _labels(result.spec) == ["W"]
    assert result.warnings == []


def test_replace_with_a_quantity_only_takeoff_drops_the_replaced_geometry(alt_pack):
    """bridge 30 CY with one line, replaced by slabs 5 CY with no elements:
    the bridge line goes; the item keeps a schema-valid placeholder line."""
    spec = apply_takeoff(sample_bridge_spec(alt_pack),
                         _wall_takeoff([("A-W1", "gidA1", 30.0)]),
                         pack=alt_pack, source_name="bridge").spec
    result = apply_takeoff(spec, _qty_only(5.0), pack=alt_pack,
                           source_name="slabs", replace=True)
    wall = _wall(result.spec)
    assert wall["qty"] == 5.0
    assert "A-W1" not in _labels(result.spec)
    assert [c["lines"] for c in wall["scaffold_meta"]["takeoffs"]] == [0]
    validate_spec(result.spec, pack=alt_pack)
    # real lines arriving later replace the placeholder
    later = apply_takeoff(result.spec, _wall_takeoff([("C-W1", "gidC1", 2.0)]),
                          pack=alt_pack, source_name="wingwalls")
    assert _labels(later.spec) == ["C-W1"]
    assert _wall(later.spec)["qty"] == 7.0


def test_reapplying_a_takeoff_with_no_elements_drops_its_old_lines(alt_pack):
    spec = apply_takeoff(sample_bridge_spec(alt_pack),
                         _wall_takeoff([("A-W1", "gidA1", 30.0)]),
                         pack=alt_pack, source_name="bridge").spec
    result = apply_takeoff(spec, _qty_only(31.0), pack=alt_pack, source_name="bridge")
    assert _wall(result.spec)["qty"] == 31.0
    assert "A-W1" not in _labels(result.spec)
    validate_spec(result.spec, pack=alt_pack)
