from __future__ import annotations

from decimal import Decimal

import pytest

from estimating_tools.heavycivil import model


def test_parse_reads_every_section(doc):
    wb = model.parse(doc)
    assert wb.estimate.id == doc["estimate"]["id"]
    assert len(wb.items) == len(doc["items"])
    assert len(wb.activities) == len(doc["activities"])
    assert len(wb.resources) == len(doc["resources"])
    assert {c.scope for c in wb.crews} == {"estimate", "library"}
    assert wb.rates_by_kind("labor")
    assert len(wb.shares) == len(doc["shares"])
    assert len(wb.source_sha) == 64


def test_decimals_are_decimal_and_nulls_none(doc):
    wb = model.parse(doc)
    m1 = next(i for i in wb.items if i.item_number == "M1")
    assert m1.estimated_unit_price == Decimal("25.00")
    twelve = next(i for i in wb.items if i.item_number == "12")
    assert twelve.estimated_unit_price is None


def test_missing_section_is_refused(doc):
    del doc["resources"]
    with pytest.raises(model.PayloadError, match="resources"):
        model.parse(doc)


def test_row_without_v_is_refused(doc):
    del doc["activities"][0]["v"]
    with pytest.raises(model.PayloadError, match=r"activities\[0\].*v"):
        model.parse(doc)


def test_dangling_activity_item_is_refused(doc):
    doc["activities"][0]["estimate_item_id"] = 999999
    with pytest.raises(model.PayloadError, match="item 999999"):
        model.parse(doc)


def test_dangling_resource_activity_is_refused(doc):
    doc["resources"][0]["activity_id"] = 999999
    with pytest.raises(model.PayloadError, match="activity 999999"):
        model.parse(doc)


def test_dangling_parent_is_refused(doc):
    child = next(a for a in doc["activities"] if a["parent_id"] is not None)
    child["parent_id"] = 999999
    with pytest.raises(model.PayloadError, match="parent 999999"):
        model.parse(doc)


def test_bad_decimal_is_refused(doc):
    doc["resources"][0]["unit_cost"] = "twelve"
    with pytest.raises(model.PayloadError, match="unit_cost"):
        model.parse(doc)


def test_crew_missing_from_payload_is_allowed(doc):
    crewed = next(a for a in doc["activities"] if a["crew_id"] is not None)
    doc["crews"] = [c for c in doc["crews"] if c["id"] != crewed["crew_id"]]
    wb = model.parse(doc)
    assert wb.crew(crewed["crew_id"]) is None


def test_source_sha_is_stable_across_key_order(doc):
    first = model.parse(doc).source_sha
    reordered = dict(reversed(list(doc.items())))
    assert model.parse(reordered).source_sha == first


def test_step_without_id_names_its_row(doc):
    stepped = next(n for n, a in enumerate(doc["activities"]) if a.get("steps"))
    del doc["activities"][stepped]["steps"][0]["id"]
    with pytest.raises(model.PayloadError, match=rf"activities\[{stepped}\]\.steps\[0\].*'id'"):
        model.parse(doc)


def test_section_that_is_not_an_object_is_refused(doc):
    doc["estimate"]["sections"] = ["Base bid"]
    with pytest.raises(model.PayloadError, match=r"estimate\.sections\[0\]"):
        model.parse(doc)


def test_member_without_id_names_its_row(doc):
    del doc["crews"][0]["members"][0]["id"]
    with pytest.raises(model.PayloadError, match=r"crews\[0\]\.members\[0\].*'id'"):
        model.parse(doc)


@pytest.mark.parametrize("count", ["two", 2.5, True, [2]])
def test_non_integer_count_is_refused(doc, count):
    doc["activities"][0]["count"] = count
    with pytest.raises(model.PayloadError, match=r"activities\[0\]\.count"):
        model.parse(doc)


def test_integer_string_count_is_read(doc):
    doc["activities"][0]["count"] = "3"
    assert model.parse(doc).activities[0].count == 3


@pytest.mark.parametrize("section", ["items", "resources", "shares"])
def test_non_object_row_is_refused(doc, section):
    doc[section].append("oops")
    with pytest.raises(model.PayloadError, match=rf"{section}\[\d+\]"):
        model.parse(doc)


def test_section_that_is_not_a_list_is_refused(doc):
    doc["items"] = {"1": doc["items"][0]}
    with pytest.raises(model.PayloadError, match="items"):
        model.parse(doc)


@pytest.mark.parametrize("section", ["items", "activities", "resources", "crews", "elements"])
def test_duplicate_ids_are_refused(doc, section):
    doc[section].append(dict(doc[section][0]))
    with pytest.raises(model.PayloadError, match=rf"{section}.*duplicate id"):
        model.parse(doc)


def test_includes_burden_defaults_to_false_like_bidsheet(doc):
    del doc["resources"][0]["includes_burden"]
    assert model.parse(doc).resources[0].includes_burden is False


def test_duplicate_step_ids_across_the_payload_are_refused(doc):
    stepped = next(a for a in doc["activities"] if a.get("steps"))
    other = next(a for a in doc["activities"] if a is not stepped)
    other["steps"] = [dict(stepped["steps"][0])]
    with pytest.raises(model.PayloadError, match=r"steps.*duplicate id"):
        model.parse(doc)


def test_duplicate_member_ids_across_crews_are_refused(doc):
    doc["crews"][1]["members"].append(dict(doc["crews"][0]["members"][0]))
    with pytest.raises(model.PayloadError, match=r"members.*duplicate id"):
        model.parse(doc)


def test_duplicate_quantity_key_in_one_element_is_refused(doc):
    element = doc["elements"][0]
    element["quantities"].append(dict(element["quantities"][0]))
    with pytest.raises(model.PayloadError, match=r"elements.*duplicate quantity key"):
        model.parse(doc)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-inf", "sNaN", float("nan"), float("inf")])
def test_non_finite_number_is_refused(doc, value):
    doc["resources"][0]["unit_cost"] = value
    with pytest.raises(model.PayloadError, match="unit_cost"):
        model.parse(doc)


def test_self_parent_is_refused(doc):
    a = doc["activities"][0]
    a["parent_id"] = a["id"]
    with pytest.raises(model.PayloadError, match=rf"activity {a['id']}: parent cycle"):
        model.parse(doc)


def test_two_cycle_is_refused(doc):
    a, b = doc["activities"][0], doc["activities"][2]
    assert a["estimate_item_id"] == b["estimate_item_id"]
    a["parent_id"], b["parent_id"] = b["id"], a["id"]
    with pytest.raises(model.PayloadError, match="parent cycle"):
        model.parse(doc)


def test_cross_item_parent_is_refused(doc):
    child = next(a for a in doc["activities"] if a["estimate_item_id"] == 2)
    other = next(a for a in doc["activities"] if a["estimate_item_id"] == 1)
    child["parent_id"] = other["id"]
    with pytest.raises(model.PayloadError, match=rf"activity {child['id']}: parent {other['id']}"):
        model.parse(doc)


def test_estimate_totals_and_activity_dates(doc):
    wb = model.parse(doc)
    assert wb.estimate.total_estimated_cost == Decimal(doc["estimate"]["totals"]["total_estimated_cost"])
    assert wb.estimate.markup_total == Decimal(doc["estimate"]["totals"]["markup_total"])
    dated = [a for a in wb.activities if a.start_date]
    assert dated and all(a.finish_date for a in dated)
    excavate = next(a for a in wb.activities if a.name == "Excavate")
    assert excavate.duration_days == Decimal("3")


@pytest.mark.parametrize("schedule, match", [
    ({"start_date": "2026-11-02", "working_weekdays": [7], "holidays": []}, "working_weekdays"),
    ({"start_date": "2026-11-02", "working_weekdays": [], "holidays": []}, "working_weekdays"),
    ({"start_date": "2026-11-02", "working_weekdays": "0-4", "holidays": []}, "working_weekdays"),
    ({"start_date": "2026-11-02", "working_weekdays": [True], "holidays": []}, "working_weekdays"),
    ({"start_date": "2026-11-02", "working_weekdays": None, "holidays": ["26/11"]}, "holidays"),
    ({"start_date": "2026-11-02", "working_weekdays": None, "holidays": "2026-11-26"}, "holidays"),
    ({"start_date": "Nov 2", "working_weekdays": None, "holidays": []}, "start_date"),
    ("weekdays", "schedule"),
])
def test_malformed_schedule_is_refused(doc, schedule, match):
    doc["estimate"]["schedule"] = schedule
    with pytest.raises(model.PayloadError, match=match):
        model.parse(doc)


def test_every_day_working_schedule_is_read(doc):
    doc["estimate"]["schedule"] = {"start_date": None, "working_weekdays": None}
    assert model.parse(doc).estimate.schedule["working_weekdays"] is None


@pytest.mark.parametrize("key", ["start_date", "finish_date", "end_date"])
def test_malformed_activity_date_is_refused(doc, key):
    doc["activities"][0][key] = "2026-13-40"
    with pytest.raises(model.PayloadError, match=rf"activities\[0\].*{key}"):
        model.parse(doc)


@pytest.mark.parametrize("sid", ['1)+HYPERLINK("http://x","y"', None, True, 1.5, [1]])
def test_non_integer_bid_total_schedule_id_is_refused(doc, sid):
    # Each id is interpolated into a SUMIF: anything but an int would be
    # formula text (or a broken formula).
    doc["estimate"]["bid_totals"][0]["schedule_ids"] = [1, sid]
    with pytest.raises(model.PayloadError,
                       match=r"estimate\.bid_totals\[0\]\.schedule_ids\[1\]: expected an integer"):
        model.parse(doc)


@pytest.mark.parametrize("value", ["1", {"id": 1}, 7])
def test_bid_total_schedule_ids_must_be_a_list_or_null(doc, value):
    doc["estimate"]["bid_totals"][0]["schedule_ids"] = value
    with pytest.raises(model.PayloadError, match=r"estimate\.bid_totals\[0\]\.schedule_ids"):
        model.parse(doc)


def test_null_bid_total_schedule_ids_cover_every_schedule(doc):
    doc["estimate"]["bid_totals"][0]["schedule_ids"] = None
    assert model.parse(doc).estimate.bid_totals[0].schedule_ids is None


@pytest.mark.parametrize("value", ["1", True, [1]])
def test_non_integer_bid_total_id_is_refused(doc, value):
    doc["estimate"]["bid_totals"][0]["id"] = value
    with pytest.raises(model.PayloadError, match=r"estimate\.bid_totals\[0\]\.id"):
        model.parse(doc)


@pytest.mark.parametrize("value", ["1", True, [1]])
def test_non_integer_section_schedule_id_is_refused(doc, value):
    doc["estimate"]["sections"][0]["schedule_id"] = value
    with pytest.raises(model.PayloadError, match=r"estimate\.sections\[0\]\.schedule_id"):
        model.parse(doc)


@pytest.mark.parametrize("value", ["1", True, [1]])
def test_non_integer_item_schedule_id_is_refused(doc, value):
    doc["items"][0]["schedule"]["id"] = value
    with pytest.raises(model.PayloadError, match=r"items\[0\]\.schedule\.id"):
        model.parse(doc)


def test_item_schedule_that_is_not_an_object_is_refused(doc):
    doc["items"][0]["schedule"] = [1]
    with pytest.raises(model.PayloadError, match=r"items\[0\]\.schedule"):
        model.parse(doc)


@pytest.mark.parametrize("section, key", [
    ("items", "id"), ("activities", "id"), ("activities", "parent_id"),
    ("activities", "crew_id"), ("resources", "id"), ("crews", "id"), ("elements", "id"),
])
@pytest.mark.parametrize("value", [[1], {"id": 1}, True, 1.5])
def test_non_scalar_ids_are_refused(doc, section, key, value):
    row = doc[section][0]
    if key == "parent_id":
        row = next(a for a in doc["activities"] if a["parent_id"] is not None)
    row[key] = value
    with pytest.raises(model.PayloadError, match=key):
        model.parse(doc)


@pytest.mark.parametrize("key", ["start_date", "finish_date"])
@pytest.mark.parametrize("value", ["0001-01-01", "9999-12-31", "1899-12-31", "2201-01-01"])
def test_activity_date_outside_the_calendar_range_is_refused(doc, key, value):
    doc["activities"][0][key] = value
    with pytest.raises(model.PayloadError, match=rf"activities\[0\].*{key}.*1900"):
        model.parse(doc)


def test_schedule_start_outside_the_calendar_range_is_refused(doc):
    doc["estimate"]["schedule"]["start_date"] = "0001-01-01"
    with pytest.raises(model.PayloadError, match="start_date"):
        model.parse(doc)


def test_compact_iso_dates_are_normalised(doc):
    doc["estimate"]["schedule"]["holidays"] = ["20261126"]
    doc["activities"][0]["start_date"] = "20261102"
    wb = model.parse(doc)
    assert wb.estimate.schedule["holidays"] == ["2026-11-26"]
    assert wb.activities[0].start_date == "2026-11-02"


def test_lookups_find_rows_by_id(doc):
    wb = model.parse(doc)
    for a in wb.activities:
        assert wb.activity(a.id) is a
    for i in wb.items:
        assert wb.item(i.id) is i
    for c in wb.crews:
        assert wb.crew(c.id) is c
    assert wb.activity(999999) is None and wb.item(None) is None and wb.crew(-1) is None


def test_resource_rate_links_are_read(doc):
    doc["resources"][0]["equipment_rate_id"] = 7
    doc["resources"][1]["material_cost_id"] = "m-3"
    wb = model.parse(doc)
    first = wb.resources[0]
    assert (first.labor_rate_id, first.equipment_rate_id, first.material_cost_id) == (None, 7, None)
    assert first.rate_link == "equipment:7"
    assert wb.resources[1].rate_link == "material:m-3"
    assert wb.resources[2].rate_link is None


def test_rate_link_is_labour_then_equipment_then_material(doc):
    doc["resources"][0].update(labor_rate_id=1, equipment_rate_id=2, material_cost_id=3)
    doc["resources"][1].update(equipment_rate_id=2, material_cost_id=3)
    wb = model.parse(doc)
    assert wb.resources[0].rate_link == "labor:1"
    assert wb.resources[1].rate_link == "equipment:2"


@pytest.mark.parametrize("key", ["labor_rate_id", "equipment_rate_id", "material_cost_id"])
@pytest.mark.parametrize("value", [[1], {"id": 1}, True, 1.5])
def test_non_scalar_rate_links_are_refused(doc, key, value):
    doc["resources"][0][key] = value
    with pytest.raises(model.PayloadError, match=rf"resources\[0\]\.{key}"):
        model.parse(doc)


def test_blank_rate_id_is_no_link(doc):
    doc["resources"][0].update(labor_rate_id="", equipment_rate_id=2)
    assert model.parse(doc).resources[0].rate_link == "equipment:2"
    doc["resources"][1].update(labor_rate_id="", equipment_rate_id="", material_cost_id="")
    assert model.parse(doc).resources[1].rate_link is None
