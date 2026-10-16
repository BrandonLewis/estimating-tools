import json
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec.cli import main
from estimating_tools.estimate_spec.format_pack import ENGINE_DIR, load_pack
from estimating_tools.estimate_spec.scaffold_save import (
    RATE_HOST_SKIP_REASON, extract_scaffold_saves)

DEMO_DIR = ENGINE_DIR / "packs" / "demo"
ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"


@pytest.fixture(scope="module")
def demo_pack():
    return load_pack(DEMO_DIR)


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
                 "--format", str(DEMO_DIR), "-o", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [s["source_item_no"] for s in doc["saves"]] == ["1"]
    reasons = {s["item_no"]: s["reason"] for s in doc["skipped"]}
    assert reasons["SETUP"] == RATE_HOST_SKIP_REASON


def test_cli_scaffold_save_end_to_end(tmp_path, capsys):
    spec_path = tmp_path / "sample-bridge.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(_spec()), encoding="utf-8")
    out = tmp_path / "scaffold_saves.json"
    assert main(["scaffold-save", "--spec", str(spec_path),
                 "--agency", "caltrans", "--format", str(DEMO_DIR),
                 "-o", str(out)]) == 0
    captured = capsys.readouterr()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [s["source_item_no"] for s in doc["saves"]] == ["4"]
    assert len(doc["skipped"]) == 3
    assert "1 saves, 3 skipped" in captured.out


def test_cli_scaffold_save_missing_spec_exits_nonzero(tmp_path, capsys):
    assert main(["scaffold-save", "--spec", str(tmp_path / "nope.yaml"),
                 "--format", str(DEMO_DIR)]) == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_scaffold_save_non_mapping_spec_exits_nonzero(tmp_path, capsys):
    spec_path = tmp_path / "sample-bridge.estimate.yaml"
    spec_path.write_text("- just\n- a list\n", encoding="utf-8")
    assert main(["scaffold-save", "--spec", str(spec_path),
                 "--format", str(DEMO_DIR)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid spec YAML" in captured.err


def test_cli_scaffold_save_non_object_code_map_exits_nonzero(tmp_path, capsys):
    spec_path = tmp_path / "sample-bridge.estimate.yaml"
    spec_path.write_text(yaml.safe_dump(_spec()), encoding="utf-8")
    codes = tmp_path / "codes.json"
    codes.write_text('["x"]', encoding="utf-8")
    assert main(["scaffold-save", "--spec", str(spec_path),
                 "--format", str(DEMO_DIR), "--code-map", str(codes)]) == 1
    assert "invalid code map JSON" in capsys.readouterr().err
