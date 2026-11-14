"""``from_model``: the read model laid out as a fieldbook config."""
import copy

import pytest

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import identity
from estimating_tools.estimate_spec.from_model import FromModelError, from_model
from estimating_tools.estimate_spec.tests._fieldbook import fieldbook_pack
from estimating_tools.estimate_spec.tests import _exchange as X


def _resource(doc, rid):
    return next(r for r in doc["resources"] if r["id"] == rid)


def _item_rows(cfg, item_no):
    return next(i for i in cfg["items"] if i["item_no"] == item_no)


def test_the_golden_read_model_lays_out_as_the_golden_config():
    assert from_model(X.payload()) == X.model_config()


def test_markup_percentage_fills_the_overhead_row():
    doc = X.payload()
    doc["estimate"]["markup_percentage"] = "10.00"
    m = from_model(doc)["markup"]
    assert m["overhead"] == {"labor": 0.1, "equipment": 0.1, "material": 0.1, "subcontract": 0.1}
    assert m["profit"] == m["insurance"] == dict.fromkeys(m["profit"], 0) and m["bond_pct"] == 0


def _mappings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "exchange":
                yield value
            yield from _mappings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _mappings(value)


def _values(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _values(value)
    else:
        yield node


def _null_every_number(doc):
    """The server's nulls (R11): every number a priced row carries."""
    for item in doc["items"]:
        item["quantity"] = None
    for res in doc["resources"]:
        res["quantity"] = res["unit_cost"] = None
    for kind in ("labor", "equipment"):
        for rate in doc["rates"][kind]:
            rate["rate"] = None
    doc["estimate"]["bid_totals"] = []


def test_no_exchange_mapping_holds_a_none():
    doc = X.payload()
    _resource(doc, 31)["time_unit"] = ""          # a blank unit is dropped too
    _null_every_number(doc)
    found = list(_mappings(from_model(doc)))
    assert found and all(v is not None and v != "" for m in found for v in m.values())


def test_a_null_server_number_is_zero_and_no_config_value_is_none():
    doc = X.payload()
    _null_every_number(doc)
    cfg = from_model(doc)
    assert None not in list(_values(cfg))
    assert [i["qty"] for i in cfg["items"]] == [0, 0]
    tasks = [t for i in cfg["items"] for t in i["labor"]]
    assert [c["count"] for t in tasks for c in t.get("crew", ())] == [0, 0, 0, 0]
    assert [(ln["qty"], ln["unit_price"]) for t in tasks for ln in t.get("lines", ())] == [
        (0, 0), (0, 0)]
    assert [r["rate"] for r in cfg["rate_table"]] == [0, 0, 0, 0, 0]


def test_an_untimed_labor_resource_is_a_labor_line():
    doc = X.payload()
    _resource(doc, 31)["time_value"] = None
    task = _item_rows(from_model(doc), "1")["labor"][0]
    assert "crew" not in task
    (line,) = task["lines"]
    assert line["cost_type"] == "labor" and line["name"] == "Superintendent"
    assert line["qty"] == 1 and line["unit_price"] == 95
    assert line["exchange"] == {"id": 31, "v": "c000000000000031"}


def test_a_rate_id_missing_from_rates_is_local():
    doc = X.payload()
    _resource(doc, 32)["labor_rate_id"] = 99
    cfg = from_model(doc)
    row = _item_rows(cfg, "2")["labor"][0]["crew"][0]
    assert row["trade"] == "Pipelayer (local)" and "ref" not in row["exchange"]
    assert {"trade": "Pipelayer (local)", "rate": 81.2, "kind": "labor"} in cfg["rate_table"]


def test_sheet_names_follow_the_spec_builds_rule():
    doc = X.payload()
    long = "Pipe / fittings: 8-inch, restrained joints and thrust blocks"
    doc["items"][0]["description"] = long
    doc["items"][1]["description"] = long
    doc["items"][1]["item_number"] = "1"
    sheets = [i["sheet"] for i in from_model(doc)["items"]]
    first = B.sheet_title(f"1 - {long.upper()}", set())
    assert sheets == [first, B.sheet_title(f"1 - {long.upper()}", {first})]
    assert sheets[0] != sheets[1] and all(len(s) <= 31 for s in sheets)
    assert not set("/:?") & set("".join(sheets))


def test_differing_shift_hours_refuse_naming_both_activities():
    doc = X.payload()
    doc["activities"][2]["hours_per_shift"] = "10.0"
    with pytest.raises(FromModelError, match=r"22.*Trench excavation.*23.*second heading"):
        from_model(doc)


def test_null_shift_hours_everywhere_default_to_eight():
    doc = X.payload()
    for act in doc["activities"]:
        act["hours_per_shift"] = None
    assert from_model(doc)["shift_hours"] == 8


@pytest.mark.parametrize("edit, word", [
    ({"parent_id": 22}, "parent"), ({"assembly_type": "PRODUCTION"}, "PRODUCTION"),
    ({"steps": [{"id": 1, "name": "s", "duration": "1", "duration_unit": "DAYS",
                 "sort_order": 0, "v": "d000000000000001"}]}, "steps")])
def test_an_activity_fieldbook_cannot_show_refuses(edit, word):
    doc = X.payload()
    doc["activities"][2].update(edit)
    with pytest.raises(FromModelError) as exc:
        from_model(doc)
    text = str(exc.value)
    assert "23" in text and "Trench excavation, second heading" in text and word in text


def test_an_item_with_no_activities_lays_out_with_no_tasks():
    doc = X.payload()
    extra = dict(doc["items"][0], id=13, item_number="3", description="Fresh item",
                 v="a000000000000013")
    doc["items"].append(extra)
    cfg = from_model(doc)
    item = _item_rows(cfg, "3")
    assert item["recipe"] == "lump_sum" and item["labor"] == []
    base = identity.Baseline(payload=doc, host=X.HOST, exported_at=X.EXPORTED_AT)
    B.generate(cfg, fieldbook_pack(), exchange=base)


def test_a_payload_the_read_model_refuses_is_a_from_model_error():
    doc = X.payload()
    doc["items"][0].pop("id")
    with pytest.raises(FromModelError):
        from_model(doc)


def test_same_name_at_different_costs_gets_its_own_local_row():
    doc = X.payload()
    laborer = copy.deepcopy(_resource(doc, 35))
    laborer.update(id=37, activity_id=23, unit_cost="44.00", sort_order=5,
                   v="c000000000000037")
    doc["resources"].append(laborer)
    cfg = from_model(doc)
    rows = {r["trade"]: r["rate"] for r in cfg["rate_table"]}
    assert rows["Laborer (local)"] == 40 and rows["Laborer (local 2)"] == 44
    crew = {c["exchange"]["id"]: c["trade"]
            for t in _item_rows(cfg, "2")["labor"] for c in t.get("crew", ())}
    assert crew[35] == "Laborer (local)" and crew[37] == "Laborer (local 2)"


def test_a_refused_activity_refuses_before_any_rate_row_is_built(monkeypatch):
    from estimating_tools.estimate_spec import from_model as FM
    monkeypatch.setattr(FM, "_rate_table", lambda *a: pytest.fail("rate table built"))
    doc = X.payload()
    doc["activities"][0]["assembly_type"] = "PRODUCTION"
    with pytest.raises(FromModelError):
        FM.from_model(doc)


def _second_pipelayer(doc, *, first=False):
    """A second library Pipelayer (labor:4, $99), and resource 32 priced from it."""
    rate = {"id": 4, "classification": "Pipelayer", "unit": "HR", "rate": "99.00"}
    labor = doc["rates"]["labor"]
    labor.insert(0, rate) if first else labor.append(rate)
    _resource(doc, 32)["labor_rate_id"] = 4
    return doc


def test_library_rates_sharing_a_name_get_unique_names_in_id_order():
    cfg = from_model(_second_pipelayer(X.payload()))
    rows = {r["exchange"]["ref"]: (r["trade"], r["rate"])
            for r in cfg["rate_table"] if "exchange" in r}
    assert rows["labor:2"] == ("Pipelayer", 81.2)
    assert rows["labor:4"] == ("Pipelayer (2)", 99)
    row = _item_rows(cfg, "2")["labor"][0]["crew"][0]
    assert row["trade"] == "Pipelayer (2)" and row["exchange"]["ref"] == "labor:4"


def test_unique_rate_names_do_not_move_with_payload_order():
    assert (from_model(_second_pipelayer(X.payload(), first=True))
            == from_model(_second_pipelayer(X.payload())))


def test_a_labor_and_an_equipment_rate_sharing_a_name_are_told_apart():
    doc = X.payload()
    doc["rates"]["equipment"][0]["name"] = "Laborer"
    names = {r["exchange"]["ref"]: r["trade"] for r in from_model(doc)["rate_table"]
             if "exchange" in r}
    assert names["labor:3"] == "Laborer" and names["equipment:5"] == "Laborer (2)"


def test_a_suffix_skips_a_name_another_rate_already_has():
    doc = _second_pipelayer(X.payload())
    doc["rates"]["labor"].append(
        {"id": 6, "classification": "Pipelayer (2)", "unit": "HR", "rate": "70.00"})
    names = {r["exchange"]["ref"]: r["trade"] for r in from_model(doc)["rate_table"]
             if "exchange" in r}
    assert names["labor:4"] == "Pipelayer (3)" and names["labor:6"] == "Pipelayer (2)"
    assert len(set(names.values())) == len(names)


def test_a_null_sort_order_and_markup_percentage_parse_as_zero():
    """``model.parse`` turns a null ``sort_order`` and ``markup_percentage``
    into 0, so the resource sort and the markup division never see None."""
    doc = X.payload()
    _resource(doc, 31)["sort_order"] = None
    doc["estimate"]["markup_percentage"] = None
    cfg = from_model(doc)
    assert cfg["markup"]["overhead"]["labor"] == 0
    assert _item_rows(cfg, "1")["labor"][0]["crew"][0]["exchange"]["id"] == 31


def test_a_blank_time_unit_on_a_days_activity_leaves_the_unit_cell_blank():
    """BidSheet.ai prices a blank ``time_unit`` in the activity's
    ``production_unit``. On a DAYS activity nothing is sent, so the crew
    row's hours formula, ``IF($Z="HOURS",1,shift)``, counts shifts (days)."""
    doc = X.payload()
    _resource(doc, 31)["time_unit"] = ""
    row = _item_rows(from_model(doc), "1")["labor"][0]["crew"][0]
    assert "time_unit" not in row["exchange"]


@pytest.mark.parametrize("unit", ["HOURS", "hours"])
def test_a_blank_time_unit_on_an_hours_activity_counts_hours(unit):
    doc = X.payload()
    _resource(doc, 31)["time_unit"] = ""
    next(a for a in doc["activities"] if a["id"] == 21)["production_unit"] = unit
    row = _item_rows(from_model(doc), "1")["labor"][0]["crew"][0]
    assert row["exchange"]["time_unit"] == "HOURS"


def test_a_resources_own_time_unit_wins_over_the_activitys():
    doc = X.payload()
    _resource(doc, 31)["time_unit"] = "DAYS"
    next(a for a in doc["activities"] if a["id"] == 21)["production_unit"] = "HOURS"
    row = _item_rows(from_model(doc), "1")["labor"][0]["crew"][0]
    assert row["exchange"]["time_unit"] == "DAYS"


def test_windows_line_endings_leave_no_carriage_return_in_notes():
    doc = X.payload()
    act = next(a for a in doc["activities"] if a["id"] == 21)
    act["description"] = "first line\r\nsecond line"
    task = _item_rows(from_model(doc), "1")["labor"][0]
    assert task["notes"] == ["first line", "second line"]
