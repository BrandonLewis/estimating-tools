import pytest

from estimating_tools.takeoff.model import CanonicalTakeoff, TakeoffRow
from estimating_tools.takeoff.push import (
    LEGACY_TARGET_WARNING, StructuresPushPlan, plan_takeoff_push,
)


def _takeoff(rows):
    return CanonicalTakeoff(organization_id=7, project_ref="RT-12", rows=rows)


# ---- LEGACY target="bid-item-quantities" (forbidden on live bids; BM #984) ----


def test_quantity_row_matching_existing_becomes_update():
    rows = [TakeoffRow(description="Formwork", kind="quantity", quantity=500, unit="SF",
                       item_number="0301", schedule="A")]
    existing = [{"item_number": "0301", "schedule": "A", "project_bid_item_id": 55}]
    plan = plan_takeoff_push(_takeoff(rows), existing, target="bid-item-quantities")
    assert plan.quantity_updates == [
        {"project_bid_item_id": 55, "item_number": "0301", "schedule": "A",
         "estimated_quantity": 500}
    ]
    assert plan.quantity_creates == []


def test_quantity_row_no_match_with_item_number_becomes_create():
    rows = [TakeoffRow(description="Curb", kind="quantity", quantity=1200, unit="LF",
                       item_number="0210", cost_code="02-100", schedule="A")]
    plan = plan_takeoff_push(_takeoff(rows), existing_bid_items=[],
                             target="bid-item-quantities")
    assert plan.quantity_creates == [
        {"item_number": "0210", "item_code": "02-100", "description": "Curb",
         "unit": "LF", "estimated_quantity": 1200, "schedule": "A"}
    ]
    assert plan.quantity_updates == []


def test_quantity_row_without_item_number_is_unresolved():
    rows = [TakeoffRow(description="Misc", kind="quantity", quantity=5, unit="EA")]
    plan = plan_takeoff_push(_takeoff(rows), existing_bid_items=[],
                             target="bid-item-quantities")
    assert plan.quantity_updates == [] and plan.quantity_creates == []
    assert len(plan.unresolved) == 1 and plan.unresolved[0]["description"] == "Misc"


def test_same_item_number_different_schedule_does_not_match():
    rows = [TakeoffRow(description="Formwork", kind="quantity", quantity=500,
                       item_number="0301", schedule="B")]
    existing = [{"item_number": "0301", "schedule": "A", "project_bid_item_id": 55}]
    plan = plan_takeoff_push(_takeoff(rows), existing, target="bid-item-quantities")
    # schedule B has no match -> a create, not an update against schedule A
    assert plan.quantity_updates == []
    assert plan.quantity_creates and plan.quantity_creates[0]["schedule"] == "B"


def test_material_and_structure_rows_are_unsupported_not_dropped():
    rows = [
        TakeoffRow(description="Class A Concrete", kind="material", quantity=40, unit="CY"),
        TakeoffRow(description="84 IN BB PP-20", kind="structure", quantity=1),
    ]
    plan = plan_takeoff_push(_takeoff(rows), existing_bid_items=[],
                             target="bid-item-quantities")
    assert {u["kind"] for u in plan.unsupported} == {"material", "structure"}
    assert plan.quantity_updates == [] and plan.quantity_creates == []


def test_item_number_match_wins_over_shared_cost_code_ordering():
    # two items share a cost code in schedule A; the row's item_number must win,
    # regardless of list order (cost_code must not shadow the item_number match)
    rows = [TakeoffRow(description="Curb 6in", kind="quantity", quantity=100,
                       item_number="0212", cost_code="12-000", schedule="A")]
    existing = [
        {"item_number": "9999", "cost_code": "12-000", "schedule": "A", "project_bid_item_id": 1},
        {"item_number": "0212", "cost_code": "12-000", "schedule": "A", "project_bid_item_id": 2},
    ]
    plan = plan_takeoff_push(_takeoff(rows), existing, target="bid-item-quantities")
    assert plan.quantity_updates[0]["project_bid_item_id"] == 2


def test_schedule_none_row_does_not_match_a_scheduled_item():
    # a row with no schedule must not match an item that lives in a schedule
    rows = [TakeoffRow(description="Misc", kind="quantity", quantity=5, item_number="0001")]
    existing = [{"item_number": "0001", "schedule": "A", "project_bid_item_id": 9}]
    plan = plan_takeoff_push(_takeoff(rows), existing, target="bid-item-quantities")
    assert plan.quantity_updates == []
    assert plan.quantity_creates and plan.quantity_creates[0]["item_number"] == "0001"


def test_item_number_present_but_unmatched_does_not_fall_back_to_cost_code():
    # item_number is authoritative: given but not found -> create, never a
    # cost_code match against a different item
    rows = [TakeoffRow(description="New curb", kind="quantity", quantity=10,
                       item_number="0299", cost_code="12-000", schedule="A")]
    existing = [{"item_number": "0212", "cost_code": "12-000", "schedule": "A",
                 "project_bid_item_id": 1}]
    plan = plan_takeoff_push(_takeoff(rows), existing, target="bid-item-quantities")
    assert plan.quantity_updates == []
    assert plan.quantity_creates and plan.quantity_creates[0]["item_number"] == "0299"


def test_cost_code_only_row_matches_only_when_unique_in_schedule():
    rows = [TakeoffRow(description="Concrete", kind="quantity", quantity=40,
                       cost_code="03-300", schedule="A")]
    # ambiguous: two items share the cost_code -> cannot safely match -> unresolved
    ambiguous = [
        {"item_number": "0301", "cost_code": "03-300", "schedule": "A", "project_bid_item_id": 1},
        {"item_number": "0302", "cost_code": "03-300", "schedule": "A", "project_bid_item_id": 2},
    ]
    plan = plan_takeoff_push(_takeoff(rows), ambiguous, target="bid-item-quantities")
    assert plan.quantity_updates == [] and len(plan.unresolved) == 1
    # unique: exactly one item carries the cost_code -> update
    unique = [{"item_number": "0301", "cost_code": "03-300", "schedule": "A", "project_bid_item_id": 1}]
    plan2 = plan_takeoff_push(_takeoff(rows), unique, target="bid-item-quantities")
    assert plan2.quantity_updates and plan2.quantity_updates[0]["project_bid_item_id"] == 1


# ---- default target="estimate-structures" (BM v2 takeoff home) ----


def _deck_row(**over):
    fields = dict(
        description="Structural Concrete, Bridge", kind="quantity", quantity=250.0,
        unit="CY", item_number="0400", cost_code="51-01", schedule="A",
        elements=[
            {"name": "S-DECK-1A2", "section_type": "decks", "count": 1,
             "length_ft": 120.0, "width_ft": 45.0, "height_ft": 1.5},
            {"name": "Wing Wall A1 West", "section_type": "wing_wall", "count": 1,
             "length_ft": 20.0, "width_ft": 1.5, "height_ft": 12.0},
            {"name": "Wing Wall A1 East", "section_type": "wing_wall", "count": 1,
             "length_ft": 20.0, "width_ft": 1.5, "height_ft": 12.0},
        ])
    fields.update(over)
    return TakeoffRow(**fields)


def test_default_target_is_estimate_structures_with_no_quantity_writes():
    plan = plan_takeoff_push(_takeoff([_deck_row()]))
    assert isinstance(plan, StructuresPushPlan)
    # NO quantity_updates/creates anywhere near the official schedule
    assert not hasattr(plan, "quantity_updates")
    assert not hasattr(plan, "quantity_creates")
    assert len(plan.structure_plans) == 1
    sp = plan.structure_plans[0]
    assert sp["item_number"] == "0400" and sp["schedule"] == "A"
    assert sp["structure_id"] == "RT-12"  # falls back to project_ref
    assert len(sp["sections"]) == 3
    deck = sp["sections"][0]
    assert deck["section_type"] == "decks"
    assert deck["custom_name"] == "S-DECK-1A2"
    assert deck["dimensions"] == {"length": 120.0, "width": 45.0, "height": 1.5}
    assert deck["allow_duplicate"] is False


def test_structures_repeated_section_type_sets_allow_duplicate():
    plan = plan_takeoff_push(_takeoff([_deck_row()]))
    wings = [s for s in plan.structure_plans[0]["sections"]
             if s["section_type"] == "wing_wall"]
    assert [w["allow_duplicate"] for w in wings] == [False, True]
    assert {w["custom_name"] for w in wings} == {"Wing Wall A1 West", "Wing Wall A1 East"}


def test_structures_element_count_expands_into_sections():
    row = _deck_row(elements=[
        {"name": "PILE", "section_type": "pile", "count": 3,
         "length_ft": None, "width_ft": None, "height_ft": 32.8084},
    ])
    plan = plan_takeoff_push(_takeoff([row]))
    sections = plan.structure_plans[0]["sections"]
    assert len(sections) == 3
    assert [s["allow_duplicate"] for s in sections] == [False, True, True]
    assert sections[0]["dimensions"] == {"length": None, "width": None, "height": 32.8084}


def test_structures_advisory_quantity_check_is_read_only_row_per_quantity():
    plan = plan_takeoff_push(_takeoff([_deck_row(), _deck_row(item_number="0401",
                                                              elements=[])]))
    assert plan.advisory_quantity_check == [
        {"item_number": "0400", "schedule": "A", "model_qty": 250.0, "unit": "CY"},
        {"item_number": "0401", "schedule": "A", "model_qty": 250.0, "unit": "CY"},
    ]


def test_structures_row_without_elements_is_unresolved_not_dropped():
    plan = plan_takeoff_push(_takeoff([_deck_row(elements=[])]))
    assert plan.structure_plans == []
    assert len(plan.unresolved) == 1
    assert "regenerate the takeoff" in plan.unresolved[0]["reason"]
    # ...but the advisory check still carries the quantity
    assert plan.advisory_quantity_check[0]["model_qty"] == 250.0


def test_structures_explicit_structure_id_wins_over_project_ref():
    plan = plan_takeoff_push(_takeoff([_deck_row()]), structure_id="BR-9")
    assert plan.structure_plans[0]["structure_id"] == "BR-9"


def test_structures_without_structure_id_or_project_ref_raises():
    takeoff = CanonicalTakeoff(organization_id=7, project_ref=None,
                               rows=[_deck_row()])
    with pytest.raises(ValueError, match=r"structure.id|structure id"):
        plan_takeoff_push(takeoff)


# ---- per-row structure_id override (issue #211) ----


def test_row_structure_id_overrides_the_fallback():
    # one takeoff, two distinct physical structures on two bid items
    rows = [_deck_row(item_number="BB-10", structure_id="Structure O1"),
            _deck_row(item_number="ALT-BB-10", structure_id="Structure O2")]
    plan = plan_takeoff_push(_takeoff(rows), structure_id="ignored-fallback")
    ids = [sp["structure_id"] for sp in plan.structure_plans]
    assert ids == ["Structure O1", "Structure O2"]


def test_row_without_structure_id_falls_back():
    # mixed: one row names its own id, the other inherits the caller's
    rows = [_deck_row(item_number="BB-13", structure_id="Splitter Box"),
            _deck_row(item_number="BB-10")]  # no structure_id -> fallback
    plan = plan_takeoff_push(_takeoff(rows), structure_id="Fallback")
    assert [sp["structure_id"] for sp in plan.structure_plans] == ["Splitter Box", "Fallback"]


def test_per_row_ids_work_without_any_global_fallback():
    # no --structure-id, no project_ref: still fine when every row carries one
    takeoff = CanonicalTakeoff(organization_id=7, project_ref=None, rows=[
        _deck_row(item_number="BB-12", structure_id="Outlet Box"),
        _deck_row(item_number="BB-13", structure_id="Splitter Box")])
    plan = plan_takeoff_push(takeoff)
    assert {sp["structure_id"] for sp in plan.structure_plans} == {"Outlet Box", "Splitter Box"}


def test_missing_fallback_raises_only_when_a_row_lacks_its_own_id():
    # project_ref None, one row has an id, the other doesn't -> still an error
    takeoff = CanonicalTakeoff(organization_id=7, project_ref=None, rows=[
        _deck_row(item_number="BB-12", structure_id="Outlet Box"),
        _deck_row(item_number="BB-10")])  # no id, no fallback
    with pytest.raises(ValueError, match=r"structure.id|structure id"):
        plan_takeoff_push(takeoff)


def test_structures_material_and_structure_rows_stay_unsupported():
    rows = [
        _deck_row(),
        TakeoffRow(description="Class A Concrete", kind="material", quantity=40, unit="CY"),
        TakeoffRow(description="84 IN BB PP-20", kind="structure", quantity=1),
    ]
    plan = plan_takeoff_push(_takeoff(rows))
    assert {u["kind"] for u in plan.unsupported} == {"material", "structure"}
    assert len(plan.structure_plans) == 1


def test_invalid_target_raises():
    with pytest.raises(ValueError, match=r"invalid target"):
        plan_takeoff_push(_takeoff([_deck_row()]), target="bid-items")


def test_legacy_target_plan_carries_the_loud_warning():
    rows = [TakeoffRow(description="Formwork", kind="quantity", quantity=500, unit="SF",
                       item_number="0301", schedule="A")]
    plan = plan_takeoff_push(_takeoff(rows), existing_bid_items=[],
                             target="bid-item-quantities")
    assert plan.WARNING == LEGACY_TARGET_WARNING
    assert plan.WARNING == ("writes OFFICIAL agency schedule quantities — "
                            "forbidden on live bids; see BM #984")
    from dataclasses import asdict
    assert asdict(plan)["WARNING"] == LEGACY_TARGET_WARNING


# ---- render_takeoff_push_plan tests (Phase 3) ----

from estimating_tools.takeoff.push import TakeoffPushPlan, render_takeoff_push_plan


def test_render_takeoff_push_plan_shape():
    plan = TakeoffPushPlan(
        quantity_updates=[{"project_bid_item_id": 42, "item_number": "1",
                            "schedule": "Base Bid", "estimated_quantity": 100.0}],
        quantity_creates=[{"item_number": "99", "item_code": "01-9900",
                            "description": "New item", "unit": "EA",
                            "estimated_quantity": 5.0, "schedule": "Base Bid"}],
        unresolved=[{"description": "no item number", "kind": "quantity",
                     "reason": "no item_number to match an existing bid item or create a new one"}],
        unsupported=[{"description": "concrete material row", "kind": "material"}],
    )
    out = render_takeoff_push_plan(plan)
    assert out.startswith("# Takeoff push plan\n\n")
    assert "1 matched, 1 created, 1 unresolved, 1 unsupported" in out
    assert "\n## Matched\n\n" in out
    assert "\n## Created\n\n" in out
    assert "\n## Unresolved\n\n" in out
    assert "\n## Unsupported\n\n" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")
    assert "## Flagged" not in out
    # the legacy render leads with the official-schedule warning
    assert "**WARNING:**" in out and "BM #984" in out


def test_render_takeoff_push_plan_empty():
    plan = TakeoffPushPlan()
    out = render_takeoff_push_plan(plan)
    assert out.startswith("# Takeoff push plan\n\n")
    assert "0 matched, 0 created, 0 unresolved, 0 unsupported" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")


def test_render_takeoff_push_plan_escapes_pipe():
    plan = TakeoffPushPlan(unresolved=[{"description": "a|b", "kind": "quantity",
                                        "reason": "some|reason"}])
    out = render_takeoff_push_plan(plan)
    assert "a\\|b" in out
    assert "some\\|reason" in out


def test_multi_classified_element_sections_planned_once(  ):
    # issue #106 addendum: a furnish-and-drive pile appears in BOTH codes'
    # rows after the multi-classification fix; its PHYSICAL section must be
    # planned once, not once per pay item.
    pile_el = {"name": "P-1", "global_id": "GPILE1", "section_type": "pile",
               "count": 1, "length_ft": 41.0, "width_ft": None,
               "height_ft": None}
    rows = [_deck_row(description="Furnish pile", item_number="129",
                      cost_code="PILE-200W-FRN", quantity=41.0, unit="LF",
                      elements=[dict(pile_el)]),
            _deck_row(description="Drive pile", item_number="130",
                      cost_code="PILE-200W-DRV", quantity=1.0, unit="EA",
                      elements=[dict(pile_el)])]
    plan = plan_takeoff_push(_takeoff(rows))
    all_sections = [s for sp in plan.structure_plans for s in sp["sections"]]
    assert len([s for s in all_sections if s["custom_name"] == "P-1"]) == 1
    # both pay items keep their advisory quantity rows — only the physical
    # section is deduped
    assert len(plan.advisory_quantity_check) == 2


def test_gidless_legacy_elements_are_never_deduped():
    # two DISTINCT physical walls can share a name in legacy takeoffs (no
    # global_id) — identity dedupe must key on global_id only
    wall = {"name": "Wall", "section_type": "walls", "count": 1,
            "length_ft": 20.0, "width_ft": 1.5, "height_ft": 12.0}
    rows = [_deck_row(elements=[dict(wall), dict(wall)])]
    plan = plan_takeoff_push(_takeoff(rows))
    assert len(plan.structure_plans[0]["sections"]) == 2


# ---- section filter: only structural solids become sections (issue #215) ----


def test_volume_measure_element_becomes_a_section():
    row = _deck_row(item_number="510053", elements=[
        {"name": "Abut 1 stem", "section_type": "walls", "count": 1,
         "length_ft": 24.75, "width_ft": 2.0, "height_ft": 15.0,
         "measure": "GrossVolume", "value_si": 21.1}])
    plan = plan_takeoff_push(_takeoff([row]))
    assert len(plan.structure_plans) == 1
    assert plan.structure_plans[0]["sections"][0]["custom_name"] == "Abut 1 stem"


def test_reinforcement_by_weight_is_pay_only_not_a_section():
    # 1,806 rebar "sections" was the motivating explosion (#215)
    row = _deck_row(item_number="520102", unit="LB", quantity=59900.0, elements=[
        {"name": "F1 transverse #7", "section_type": "reinforcingbar", "count": 1,
         "length_ft": 289.0, "width_ft": None, "height_ft": None,
         "measure": "GrossWeight", "value_si": 27170.0}])
    plan = plan_takeoff_push(_takeoff([row]))
    assert plan.structure_plans == []           # no section
    # ...but the pay quantity still rides the advisory check
    assert plan.advisory_quantity_check == [
        {"item_number": "520102", "schedule": "A", "model_qty": 59900.0, "unit": "LB"}]


def test_length_paid_barrier_is_pay_only_but_its_cy_companion_sections():
    # the dual-measure barrier: the LF pay row rides advisory; the CY
    # companion (same Caltrans item, GrossVolume) is the concrete section
    lf = _deck_row(description="Barrier 842 LF", item_number="839741", unit="LF",
                   quantity=171.0, elements=[
        {"name": "Type 842", "global_id": "GB842", "section_type": "railing",
         "count": 1, "length_ft": 171.0, "width_ft": None, "height_ft": None,
         "measure": "Length", "value_si": 52.1}])
    cy = _deck_row(description="Barrier 842 CY", item_number="839741a", unit="CY",
                   quantity=28.34, elements=[
        {"name": "Type 842 concrete", "global_id": "GB842CY",
         "section_type": "railing", "count": 1, "length_ft": 171.0,
         "width_ft": 1.5, "height_ft": 3.0, "measure": "GrossVolume",
         "value_si": 21.67}])
    plan = plan_takeoff_push(_takeoff([lf, cy]))
    assert len(plan.structure_plans) == 1
    assert plan.structure_plans[0]["item_number"] == "839741a"
    assert len(plan.advisory_quantity_check) == 2   # both rows keep their qty


def test_pile_drive_by_count_is_pay_only_even_sharing_the_furnish_global_id():
    # #106 + #215: furnish (Length) and drive (Count) are the SAME physical
    # pile — one global_id. Drive is pay-only and must NOT reserve that shared
    # id ahead of the furnish row that sections it, even when listed FIRST: the
    # dedupe runs over solids only, so the filtered-out drive never claims it.
    drive = _deck_row(description="Drive pile", item_number="490555", unit="EA",
                      quantity=20.0, elements=[
        {"name": "Pile", "global_id": "GP1", "section_type": "pile",
         "count": 20, "length_ft": None, "width_ft": None, "height_ft": None,
         "measure": "Count", "value_si": 20.0}])
    furnish = _deck_row(description="Furnish pile", item_number="490550", unit="LF",
                        quantity=822.0, elements=[
        {"name": "Pile", "global_id": "GP1", "section_type": "pile",
         "count": 1, "length_ft": 822.0, "width_ft": None, "height_ft": None,
         "measure": "Length", "value_si": 250.6}])
    plan = plan_takeoff_push(_takeoff([drive, furnish]))   # drive listed FIRST
    assert len(plan.structure_plans) == 1                  # furnish only
    assert plan.structure_plans[0]["item_number"] == "490550"
    assert len(plan.structure_plans[0]["sections"]) == 1   # not 20 drive copies
    assert len(plan.advisory_quantity_check) == 2          # both rows keep qty


def test_measureless_elements_still_section_backward_compatible():
    # pre-0.1.32 takeoffs carry no `measure`; they must section exactly as
    # before so the filter is a no-op on legacy data
    plan = plan_takeoff_push(_takeoff([_deck_row()]))
    assert len(plan.structure_plans[0]["sections"]) == 3


def test_row_with_only_pay_only_elements_is_not_reported_unresolved():
    # a filtered-to-pay-only row is intentional, NOT the "no elements" error
    row = _deck_row(item_number="519088", unit="LF", quantity=50.0, elements=[
        {"name": "Joint seal", "section_type": "covering", "count": 1,
         "length_ft": 50.0, "width_ft": None, "height_ft": None,
         "measure": "Length", "value_si": 15.24}])
    plan = plan_takeoff_push(_takeoff([row]))
    assert plan.structure_plans == []
    assert plan.unresolved == []                 # not flagged as missing elements
    assert plan.advisory_quantity_check[0]["item_number"] == "519088"


# ---- signed cy / volume_factor passthrough (issue #210) ----


def test_explicit_cy_passes_through_to_section_dimensions():
    # an element that knows its volume but not a full L×W×H box (swept solid)
    row = _deck_row(elements=[
        {"name": "Wall", "section_type": "walls", "count": 1,
         "length_ft": None, "width_ft": None, "height_ft": 6.25,
         "measure": "GrossVolume", "value_si": 3.1, "cy": 4.0553}])
    dims = plan_takeoff_push(_takeoff([row])).structure_plans[0]["sections"][0]["dimensions"]
    assert dims == {"length": None, "width": None, "height": 6.25, "cy": 4.0553}


def test_signed_cy_deduct_rides_negative_not_a_negated_dimension():
    # the Tanner deduct: a −31.5 CY subtraction is an honest signed cy, no
    # more negated box dimensions (the workaround #210 removes)
    row = _deck_row(elements=[
        {"name": "Ramp notch deduct", "section_type": "invert", "count": 1,
         "length_ft": None, "width_ft": None, "height_ft": None,
         "measure": "GrossVolume", "value_si": -24.08, "cy": -31.5}])
    dims = plan_takeoff_push(_takeoff([row])).structure_plans[0]["sections"][0]["dimensions"]
    assert dims["cy"] == -31.5
    assert dims["length"] is None                 # NOT a negated length


def test_volume_factor_passes_through_for_a_wedge():
    row = _deck_row(elements=[
        {"name": "Sloping ramp slab", "section_type": "invert", "count": 1,
         "length_ft": 20.0, "width_ft": 8.0, "height_ft": 1.5,
         "volume_factor": 0.5}])
    dims = plan_takeoff_push(_takeoff([row])).structure_plans[0]["sections"][0]["dimensions"]
    assert dims == {"length": 20.0, "width": 8.0, "height": 1.5, "volume_factor": 0.5}


def test_box_only_element_gets_no_cy_or_volume_factor_keys():
    # backward compatible: absent cy/volume_factor -> dimensions unchanged
    dims = plan_takeoff_push(_takeoff([_deck_row()])).structure_plans[0]["sections"][0]["dimensions"]
    assert dims == {"length": 120.0, "width": 45.0, "height": 1.5}
    assert "cy" not in dims and "volume_factor" not in dims
