import json
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec.cli import main
from estimating_tools.estimate_spec.format_pack import ENGINE_DIR, load_pack
from estimating_tools.estimate_spec.scaffold_save import (
    RATE_HOST_SKIP_REASON, extract_scaffold_saves)

LEGACY_DIR = ENGINE_DIR / "tests" / "fixtures" / "packs" / "legacy_demo"
ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"


@pytest.fixture(scope="module")
def demo_pack():
    return load_pack(LEGACY_DIR)


@pytest.fixture(scope="module")
def alt_pack():
    return load_pack(ALT_DIR)


def _demo_spec_with_rate_host():
    return {
        "project": {"name": "Demo Project"},
        "items": [
            {"recipe": "setup", "item_no": "SETUP", "description": "Setup",
             "uom": "LS", "qty": 1.0, "labor": []},
            {"recipe": "line_item", "item_no": "1", "description": "Trench",
             "uom": "LF", "qty": 100.0, "cost_code": "02-310", "labor": []},
        ],
    }


def _spec():
    return {
        "project": {"name": "Sample Bridge"},
        "items": [
            {"recipe": "standard_item", "item_no": "4",
             "description": "Structural Concrete", "uom": "CY", "qty": 412.0,
             "cost_code": "510120",
             "labor": [
                 {"slot": "A", "description": "Form deck",
                  "crew": [{"trade": "CARP", "count": 4, "days": 10.0},
                           {"trade": "LAB", "count": 2, "days": 8.0}]},
                 {"slot": "B", "description": "Place/finish",
                  "crew": [{"trade": "LAB", "count": 6, "days": 10.6}]},
             ],
             "scaffold_meta": {"schedule": "Base Bid"}},
            {"recipe": "preamble", "item_no": "1",
             "description": "Mobilization", "uom": "LS", "qty": 1.0,
             "labor": [{"slot": "A", "description": "Mob",
                        "crew": [{"trade": "FORE", "days": 2.0}]}]},
            {"recipe": "standard_item", "item_no": "7",
             "description": "Minor Concrete", "uom": "CY", "qty": 50.0,
             "labor": [{"slot": "A", "description": "Place",
                        "crew": [{"trade": "LAB", "days": "=D4*2"}]}],
             "scaffold_meta": {"schedule": "Base Bid"}},
            {"recipe": "standard_item", "item_no": "9",
             "description": "", "uom": "EA", "qty": 3.0, "cost_code": "x",
             "labor": []},
        ],
    }


def test_extracts_save_with_production(alt_pack):
    saves, skipped = extract_scaffold_saves(
        _spec(), agency="caltrans", saved_on="2026-08-03", pack=alt_pack)
    save = saves[0]
    assert save["bid_item_code"] == "510120"
    assert save["agency"] == "caltrans"
    assert save["name"] == "Structural Concrete"
    # duration = max(10, 8) + 10.6 = 20.6 days -> 412 / 20.6 = 20 CY/day
    assert save["default_production"] == {"rate": 20.0, "rate_unit": "CY/day"}
    assert save["notes"] == "saved from Sample Bridge item 4 on 2026-08-03"
    assert save["source_item_no"] == "4"


def test_cost_code_only_when_distinct_from_bid_item_code(alt_pack):
    # cost_code IS the bid item code (no code map): org cost_codes unknown
    saves, _ = extract_scaffold_saves(_spec(), pack=alt_pack)
    assert saves[0]["cost_codes"] == []
    # code map supplies the agency code: cost_code is the org code
    saves, _ = extract_scaffold_saves(
        _spec(), code_map={"Base Bid::4": "510120X"}, pack=alt_pack)
    assert saves[0]["bid_item_code"] == "510120X"
    assert saves[0]["cost_codes"] == ["510120"]


def test_code_map_precedence_schedule_qualified_then_plain(alt_pack):
    saves, _ = extract_scaffold_saves(
        _spec(), code_map={"Base Bid::4": "AAA", "4": "BBB"}, pack=alt_pack)
    assert saves[0]["bid_item_code"] == "AAA"
    saves, _ = extract_scaffold_saves(_spec(), code_map={"4": "BBB"}, pack=alt_pack)
    assert saves[0]["bid_item_code"] == "BBB"


def test_formula_days_omit_production(alt_pack):
    saves, _ = extract_scaffold_saves(_spec(), code_map={"7": "730020"}, pack=alt_pack)
    item7 = [s for s in saves if s["source_item_no"] == "7"][0]
    assert "default_production" not in item7


def test_skips_reported_not_silent(alt_pack):
    saves, skipped = extract_scaffold_saves(_spec(), pack=alt_pack)
    reasons = {s["item_no"]: s["reason"] for s in skipped}
    assert "rate-host item" in reasons["1"]
    assert "no description" in reasons["9"]
    assert "no bid_item_code" in reasons["7"]   # no cost_code, no map
    assert [s["source_item_no"] for s in saves] == ["4"]


def test_project_ref_override_and_no_date(alt_pack):
    saves, _ = extract_scaffold_saves(_spec(), project_ref="sample-bridge", pack=alt_pack)
    assert saves[0]["notes"] == "saved from sample-bridge item 4"


# ---- pack-driven rate-host skip (Plan C Task 5) -----------------------------

def test_scaffold_save_skips_pack_rate_host(demo_pack):
    """The demo pack's rate-host recipe is `setup`, not the reference pack's
    `mob_item` — a hardcoded 'mob_item' literal coming back would let SETUP
    through as a save instead of skipping it."""
    saves, skipped = extract_scaffold_saves(
        _demo_spec_with_rate_host(), pack=demo_pack)
    reasons = {s["item_no"]: s["reason"] for s in skipped}
    assert reasons["SETUP"] == RATE_HOST_SKIP_REASON
    assert [s["source_item_no"] for s in saves] == ["1"]


def test_cli_scaffold_save_resolves_pack_via_format(tmp_path, capsys):
    spec_path = tmp_path / "demo.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(_demo_spec_with_rate_host()),
                         encoding="utf-8")
    out = tmp_path / "scaffold_saves.json"
    assert main(["scaffold-save", "--spec", str(spec_path),
                 "--format", str(LEGACY_DIR), "-o", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [s["source_item_no"] for s in doc["saves"]] == ["1"]
    reasons = {s["item_no"]: s["reason"] for s in doc["skipped"]}
    assert reasons["SETUP"] == RATE_HOST_SKIP_REASON


def test_cli_scaffold_save_end_to_end(tmp_path, capsys):
    spec_path = tmp_path / "sample-bridge.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(_spec()), encoding="utf-8")
    out = tmp_path / "scaffold_saves.json"
    assert main(["scaffold-save", "--spec", str(spec_path),
                 "--agency", "caltrans", "--format", str(LEGACY_DIR),
                 "-o", str(out)]) == 0
    captured = capsys.readouterr()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [s["source_item_no"] for s in doc["saves"]] == ["4"]
    assert len(doc["skipped"]) == 3
    assert "1 saves, 3 skipped" in captured.out


def test_cli_scaffold_save_missing_spec_exits_nonzero(tmp_path, capsys):
    assert main(["scaffold-save", "--spec", str(tmp_path / "nope.yaml"),
                 "--format", str(LEGACY_DIR)]) == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_scaffold_save_non_mapping_spec_exits_nonzero(tmp_path, capsys):
    spec_path = tmp_path / "sample-bridge.estimate.yaml"
    spec_path.write_text("- just\n- a list\n", encoding="utf-8")
    assert main(["scaffold-save", "--spec", str(spec_path),
                 "--format", str(LEGACY_DIR)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid spec YAML" in captured.err


def test_cli_scaffold_save_non_object_code_map_exits_nonzero(tmp_path, capsys):
    spec_path = tmp_path / "sample-bridge.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(_spec()), encoding="utf-8")
    codes = tmp_path / "codes.json"
    codes.write_text('["x"]', encoding="utf-8")
    assert main(["scaffold-save", "--spec", str(spec_path),
                 "--format", str(LEGACY_DIR), "--code-map", str(codes)]) == 1
    assert "invalid code map JSON" in capsys.readouterr().err


# ---- the rate host is the injected host, not every item of its recipe -----
# (fieldbook phase 3b: fieldbook's rate_host_recipe is `lump_sum`, the recipe of
# its real lump-sum bid items; its rate table lives on the Rates book sheet.)

FIELDBOOK_DIR = ENGINE_DIR / "packs" / "fieldbook"


def _injected_host(recipe):
    """The rate-table host `scaffold` injects when no mobilization item was
    selected (scaffold.py: item_no RATES, source scaffold:rate_host)."""
    return {"recipe": recipe, "sheet": "Setup", "item_no": "RATES",
            "description": "Rate table host (no mobilization item selected)",
            "uom": "LS", "qty": 0, "labor": [],
            "scaffold_meta": {"source": "scaffold:rate_host", "schedule": None,
                              "official_qty": None, "field_hashes": {}}}


def test_fieldbook_saves_its_lump_sum_bid_items_and_skips_only_the_injected_host():
    pack = load_pack(FIELDBOOK_DIR)
    assert pack.seed["scaffold"]["rate_host_recipe"] == "lump_sum"   # shared with bid items
    spec = {"project": {"name": "Demo Pipeline"}, "items": [
        _injected_host("lump_sum"),
        {"recipe": "lump_sum", "item_no": "1", "description": "Mobilization",
         "uom": "LS", "qty": 1, "cost_code": "999990", "labor": [],
         "scaffold_meta": {"source": "bid_frame", "schedule": "Base Bid"}},
        {"recipe": "line_item", "item_no": "2", "description": "8in water main",
         "uom": "LF", "qty": 100, "cost_code": "150100", "labor": []},
    ]}
    saves, skipped = extract_scaffold_saves(spec, pack=pack)
    assert [(s["source_item_no"], s["bid_item_code"], s["name"]) for s in saves] == [
        ("1", "999990", "Mobilization"), ("2", "150100", "8in water main")]
    assert skipped == [{"item_no": "RATES", "reason": RATE_HOST_SKIP_REASON}]


def test_legacy_demo_still_skips_every_item_of_its_rate_host_recipe(demo_pack):
    """legacy_demo keeps its rate table on the host item's own sheet, so every
    `setup` item -- a selected mobilization item or the injected host -- is
    the rate host and is skipped, exactly as before."""
    spec = _demo_spec_with_rate_host()
    spec["items"].insert(0, _injected_host("setup"))
    saves, skipped = extract_scaffold_saves(spec, pack=demo_pack)
    assert skipped == [{"item_no": "RATES", "reason": RATE_HOST_SKIP_REASON},
                       {"item_no": "SETUP", "reason": RATE_HOST_SKIP_REASON}]
    assert [s["source_item_no"] for s in saves] == ["1"]


def test_a_real_fieldbook_scaffold_saves_everything_but_its_injected_host():
    """End to end: scaffold a fieldbook spec from a bid frame with no
    mobilization item (so scaffold injects the RATES host), then extract:
    only the injected host is skipped as the rate host."""
    from estimating_tools.estimate_spec.scaffold import scaffold_spec
    from estimating_tools.estimate_spec.tests.test_scaffold import _non_mob_bid_items

    pack = load_pack(FIELDBOOK_DIR)
    result = scaffold_spec(_non_mob_bid_items(), items="all", pack=pack)
    assert result.injected_rate_host
    spec = result.spec
    bid_items = [it["item_no"] for it in spec["items"] if it["item_no"] != "RATES"]
    assert bid_items
    saves, skipped = extract_scaffold_saves(spec, pack=pack)
    rate_host_skips = [s for s in skipped if s["reason"] == RATE_HOST_SKIP_REASON]
    assert rate_host_skips == [{"item_no": "RATES", "reason": RATE_HOST_SKIP_REASON}]
    assert sorted([s["source_item_no"] for s in saves]
                  + [s["item_no"] for s in skipped if s not in rate_host_skips]) == sorted(bid_items)


@pytest.mark.parametrize("host", [
    {"item_no": "1A", "scaffold_meta": {"source": "scaffold:rate_host"}},  # item_no edited
    {"item_no": "RATES"},                                                  # no scaffold_meta
])
def test_fieldbook_finds_the_injected_host_by_either_marker(host):
    from estimating_tools.estimate_spec.format_pack import is_rate_host

    pack = load_pack(FIELDBOOK_DIR)
    item = {"recipe": "lump_sum", "description": "Rate table host", "uom": "LS",
            "qty": 0, "cost_code": "999990", "labor": [], **host}
    assert is_rate_host(item, pack)
    saves, skipped = extract_scaffold_saves({"items": [item]}, pack=pack)
    assert saves == []
    assert skipped == [{"item_no": host["item_no"], "reason": RATE_HOST_SKIP_REASON}]


def test_the_schemas_plain_text_project_names_the_saves(alt_pack):
    """The skeleton schema's `project` is plain text; a schema-valid spec
    (every scaffolded or hand-written one) must not crash scaffold-save when
    no --project-ref is given."""
    spec = _spec()
    spec["project"] = "Sample Bridge"
    saves, _ = extract_scaffold_saves(spec, pack=alt_pack)
    assert saves[0]["notes"] == "saved from Sample Bridge item 4"
