"""Cross-reference validation for the estimate spec (Phase 4.5).

Covers references JSON Schema cannot express: crew_id → crews[].id and
crews[].members[].trade → rate_table[].trade. Each failure mode gets a
locator in the ValueError message so authors can jump to the offending row.
"""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.validate import validate_cross_references


def _base():
    return {
        "project": "Sample",
        "markup": 100,
        "rate_table": [{"trade": "FORE", "rate": 150}, {"trade": "LAB", "rate": 90}],
        "items": [
            {"item_no": "Item # 1", "recipe": "mob_item", "sheet": "MOB",
             "description": "Mob", "uom": "LS", "labor": []},
        ],
    }


def test_valid_config_no_new_fields_passes():
    validate_cross_references(_base())


def test_valid_config_with_crews_and_crew_id_passes():
    cfg = _base()
    cfg["crews"] = [
        {"id": "crew_lab_2", "description": "2 labs",
         "members": [{"trade": "LAB", "count": 2}]},
    ]
    cfg["items"][0]["crew_id"] = "crew_lab_2"
    validate_cross_references(cfg)


def test_crew_id_missing_reference_raises_with_locator():
    cfg = _base()
    cfg["items"][0]["crew_id"] = "crew_nonexistent"
    with pytest.raises(ValueError, match=r"Item # 1.*crew_nonexistent"):
        validate_cross_references(cfg)


def test_crew_id_set_but_no_crews_section_raises():
    cfg = _base()
    cfg["items"][0]["crew_id"] = "crew_lab_2"
    # No cfg["crews"]
    with pytest.raises(ValueError, match=r"Item # 1.*crew_lab_2"):
        validate_cross_references(cfg)


def test_duplicate_crew_id_raises_citing_both_indexes():
    cfg = _base()
    cfg["crews"] = [
        {"id": "crew_dup", "members": [{"trade": "LAB", "count": 1}]},
        {"id": "crew_dup", "members": [{"trade": "FORE", "count": 1}]},
    ]
    with pytest.raises(ValueError, match=r"crew_dup.*index 0.*index 1"):
        validate_cross_references(cfg)


def test_crew_member_trade_not_in_rate_table_raises():
    cfg = _base()
    cfg["crews"] = [
        {"id": "crew_bad", "members": [{"trade": "PLUMB", "count": 1}]},
    ]
    with pytest.raises(ValueError, match=r"crew_bad.*PLUMB"):
        validate_cross_references(cfg)


def test_empty_crews_array_is_valid():
    cfg = _base()
    cfg["crews"] = []
    validate_cross_references(cfg)


def test_no_crews_no_crew_id_passes():
    # Regression: existing configs without any of the new machinery must not trip.
    validate_cross_references(_base())


def test_crew_missing_id_raises_with_locator():
    cfg = _base()
    cfg["crews"] = [{"members": [{"trade": "LAB", "count": 1}]}]     # no id
    with pytest.raises(ValueError, match=r"crews\[0\].*missing required 'id'"):
        validate_cross_references(cfg)


def test_crew_missing_members_raises_with_locator():
    cfg = _base()
    cfg["crews"] = [{"id": "crew_no_members"}]                        # no members
    with pytest.raises(ValueError, match=r"crew_no_members.*missing or empty 'members'"):
        validate_cross_references(cfg)


def test_crew_empty_members_raises_with_locator():
    cfg = _base()
    cfg["crews"] = [{"id": "crew_empty", "members": []}]
    with pytest.raises(ValueError, match=r"crew_empty.*missing or empty 'members'"):
        validate_cross_references(cfg)


def test_crew_member_missing_trade_raises_with_locator():
    cfg = _base()
    cfg["crews"] = [{"id": "crew_x", "members": [{"count": 2}]}]      # no trade
    with pytest.raises(ValueError, match=r"crew_x.*members\[0\].*missing required 'trade'"):
        validate_cross_references(cfg)
