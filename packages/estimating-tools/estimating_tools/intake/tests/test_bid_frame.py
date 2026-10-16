"""Normalize MCP bid items; seed a takeoff_map skeleton keyed like calc-bim's."""
import yaml

from estimating_tools.intake.bid_frame import (
    infer_measure, normalize_bid_items, takeoff_map_skeleton,
)
from estimating_tools.intake.manifest import BidFrameItem

RAW = [  # field spellings as the BidSheet.ai MCP returns them
    {"id": 901, "item_number": "0010", "schedule_name": "A",
     "item_code": "03 30 00", "description": "Structure concrete",
     "unit": "CY", "estimated_quantity": 120.0},
    {"project_bid_item_id": 902, "item_number": "0020", "schedule": "A",
     "cost_code": "32 16 13", "description": "Curb & gutter", "unit": "LF"},
    {"id": 903, "item_number": "0030", "schedule_name": "B",
     "description": "Mobilization", "unit": "LS"},   # no code
]


def test_normalize_tolerates_field_spellings():
    items = normalize_bid_items(RAW)
    assert [i.project_bid_item_id for i in items] == [901, 902, 903]
    assert items[0].schedule == "A" and items[1].schedule == "A"
    assert items[0].item_code == "03 30 00"
    assert items[1].item_code == "32 16 13"   # cost_code accepted
    assert items[2].item_code is None
    assert items[0].estimated_quantity == 120.0
    assert items[1].estimated_quantity is None


def test_normalize_requires_item_number():
    import pytest
    with pytest.raises(ValueError, match="missing item_number"):
        normalize_bid_items([{"id": 9, "schedule_name": "A"}])


def test_infer_measure():
    assert infer_measure("CY") == "GrossVolume"
    assert infer_measure("SF") == "GrossArea"
    assert infer_measure("LF") == "Length"
    assert infer_measure("EA") == "Count"
    assert infer_measure("TON") is None


def test_takeoff_map_skeleton_is_valid_yaml_keyed_by_code():
    items = normalize_bid_items(RAW)
    text = takeoff_map_skeleton(items, organization_id=7, project_ref="job-x")
    data = yaml.safe_load(text)
    assert data["organization_id"] == 7
    assert data["project_ref"] == "job-x"
    assert data["defaults"]["schedule"] == "A"   # most common schedule
    code = data["codes"]["03 30 00"]
    assert code == {"measure": "GrossVolume", "unit": "CY",
                    "item_number": "0010", "schedule": "A"}
    assert data["codes"]["32 16 13"]["measure"] == "Length"
    # the code-less item is surfaced in a comment, not silently dropped
    assert "0030" in text and "Mobilization" in text
    assert "0030" not in str(data.get("codes"))


def test_duplicate_item_code_first_wins_and_losers_surfaced():
    items = normalize_bid_items([
        {"id": 1, "item_number": "0010", "schedule_name": "A",
         "item_code": "03 30 00", "description": "Conc A", "unit": "CY"},
        {"id": 2, "item_number": "0110", "schedule_name": "B",
         "item_code": "03 30 00", "description": "Conc B", "unit": "CY"},
    ])
    text = takeoff_map_skeleton(items, organization_id=7)
    data = yaml.safe_load(text)
    assert data["codes"]["03 30 00"]["item_number"] == "0010"  # first wins
    assert "0110" in text and "Conc B" in text                  # loser surfaced
    assert "sharing an already-mapped cost code" in text


def test_multiline_description_stays_commented():
    items = normalize_bid_items([
        {"id": 1, "item_number": "0010", "schedule_name": "A",
         "description": "Line one\nLine two", "unit": "LS"},
    ])
    text = takeoff_map_skeleton(items, organization_id=7)
    assert yaml.safe_load(text) is not None   # file still parses
    assert "Line one Line two" in text


def test_live_payload_quantity_field_is_snapshotted():
    items = normalize_bid_items([
        {"id": 1, "item_number": "0010", "schedule_name": "A",
         "item_code": "03 30 00", "unit": "CY", "quantity": "100"}])
    assert items[0].estimated_quantity == 100.0


def test_unconvertible_pay_unit_excluded_from_codes_and_surfaced():
    items = normalize_bid_items([
        {"id": 1, "item_number": "0040", "schedule_name": "A",
         "item_code": "31 23 00", "description": "Imported borrow",
         "unit": "TON"}])
    text = takeoff_map_skeleton(items, organization_id=7)
    data = yaml.safe_load(text)
    assert "31 23 00" not in (data.get("codes") or {})
    assert "cannot convert" in text and "0040" in text


def test_zero_ids_preserved():
    items = normalize_bid_items([
        {"project_bid_item_id": 0, "item_number": 0, "schedule_name": "A",
         "unit": " CY "}])
    assert items[0].project_bid_item_id == 0
    assert items[0].item_number == "0"
    text = takeoff_map_skeleton(items, organization_id=7)
    assert yaml.safe_load(text) is not None


def test_scheduleless_item_omits_schedule_key():
    items = normalize_bid_items([
        {"id": 1, "item_number": "0010", "item_code": "03 30 00", "unit": "CY"}])
    text = takeoff_map_skeleton(items, organization_id=7)
    data = yaml.safe_load(text)
    # a present-but-null schedule would override est-bim defaults.schedule
    assert "schedule" not in data["codes"]["03 30 00"]
