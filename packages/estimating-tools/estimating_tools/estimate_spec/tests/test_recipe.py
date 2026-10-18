"""The recipe-expansion engine (pure; no workbook)."""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec import recipe as R

ITEM = {"item_no": "7", "notes": ["a", "b"], "qty": 3,
        "takeoff": {"kind": "geometry", "lines": [1]},
        "labor": [{"slot": "A"}, {"slot": "B"}],
        "cost_details": [{"name": "LUMBER"}, {"name": "FUEL", "header_price": 4}]}
CONFIG = {"rate_table": [{"trade": "X", "rate": 1}], "bid_date": "2026-09-17"}


def scopes(**extra):
    return {"item": ITEM, "config": CONFIG, "span": {}, "exports": {}, **extra}


# ---- expand -----------------------------------------------------------------

def test_a_whole_token_yields_the_raw_value():
    assert R.expand("{item.notes}", scopes()) == ["a", "b"]
    assert R.expand("{item.takeoff}", scopes())["kind"] == "geometry"
    assert R.expand("{item.qty}", scopes()) == 3


def test_embedded_tokens_are_stringified():
    assert R.expand("Item {item.item_no} x{item.qty}", scopes()) == "Item 7 x3"


def test_write_time_tokens_are_left_verbatim():
    t = "=G{row:total}/{item_qty}+{p.x}+{ref:a.b}+{r-1}"
    assert R.expand(t, scopes()) == t


def test_tokens_nest_inner_first():
    s = scopes(it={"name": "LUMBER"})
    assert (R.expand("={ref:cost_detail[{it.name}].subtotal}", s)
            == "={ref:cost_detail[LUMBER].subtotal}")


def test_it_is_left_alone_when_unbound():
    assert R.expand("{it.name}", scopes()) == "{it.name}"


def test_a_missing_path_in_a_template_is_an_error():
    with pytest.raises(R.RecipeError, match="nope"):
        R.expand("{item.nope}", scopes())


def test_span_tokens():
    s = scopes(span={"labor_block": (10, 40)})
    assert R.expand("{span:labor_block.first}", s) == 10
    assert R.expand("{span:labor_block.last}", s) == 40
    assert R.expand("{span:nothing.first}", s) is None      # == old labor_span [None, None]
    with pytest.raises(R.RecipeError):
        R.expand("{span:labor_block.middle}", s)


# ---- resolve_value ----------------------------------------------------------

def test_from_default_matches_dict_get_semantics():
    assert R.resolve_value({"from": "item.qty", "default": 1}, scopes()) == 3
    assert R.resolve_value({"from": "item.absent", "default": 1}, scopes()) == 1
    item = dict(ITEM, qty=None)
    assert R.resolve_value({"from": "item.qty", "default": 1},
                           dict(scopes(), item=item)) is None   # present-but-None is kept


def test_for_each_as_builds_a_list():
    v = {"for_each": "item.cost_details",
         "as": {"name": "{it.name}", "factor": 1,
                "source_ref": "={ref:cost_detail[{it.name}].subtotal}"}}
    assert R.resolve_value(v, scopes()) == [
        {"name": "LUMBER", "factor": 1, "source_ref": "={ref:cost_detail[LUMBER].subtotal}"},
        {"name": "FUEL", "factor": 1, "source_ref": "={ref:cost_detail[FUEL].subtotal}"},
    ]


def test_for_each_over_a_missing_list_is_empty():
    assert R.resolve_value({"for_each": "item.absent", "as": "{it}"}, scopes()) == []


def test_sum_existing_keeps_order_and_skips_the_unpublished():
    s = scopes(exports={"labor_rollup.labor_total": "$G$9", "takeoff.sub_spread_total": "$G$3"})
    v = {"sum_existing": ["labor_rollup.labor_total", "spreads.materials_total",
                         "summary_rollup.summary_total", "takeoff.sub_spread_total"]}
    assert R.resolve_value(v, s) == "=SUM({ref:labor_rollup.labor_total},{ref:takeoff.sub_spread_total})"


# ---- entries ----------------------------------------------------------------

def test_when_guard():
    assert R.is_active({"unit": "u", "when": "item.notes"}, scopes())
    assert not R.is_active({"unit": "u", "when": "item.spreads"}, scopes())
    assert R.is_active({"unit": "u"}, scopes())


def test_variant_selection():
    doc = {"takeoff_variants": {"geometry": "takeoff_geometry"}}
    e = {"unit": "takeoff", "variant_from": "item.takeoff.kind", "variants": "takeoff_variants"}
    assert R.concrete_unit(e, scopes(), doc) == "takeoff_geometry"
    assert R.concrete_unit({"unit": "notes_band"}, scopes(), doc) == "notes_band"


def test_an_unknown_variant_kind_is_a_recipe_error_naming_entry_and_kind():
    doc = {"takeoff_variants": {"geometry": "takeoff_geometry"}}
    e = {"unit": "takeoff", "variant_from": "item.takeoff.kind", "variants": "takeoff_variants"}
    item = {**ITEM, "takeoff": {"kind": "sonar"}}
    with pytest.raises(R.RecipeError, match=r"takeoff.*'sonar'"):
        R.concrete_unit(e, scopes(item=item), doc)


def test_for_each_instances_with_keys():
    e = {"unit": "labor_block", "for_each": "item.labor", "key": "labor[{it.slot}]", "params": "{it}"}
    assert R.instances(e, scopes()) == [("labor[A]", {"slot": "A"}), ("labor[B]", {"slot": "B"})]


def test_singleton_instance_has_no_key():
    e = {"unit": "item_header", "params": {"item_no": "{item.item_no}",
                                           "bid_date": {"from": "config.bid_date", "default": ""}}}
    assert R.instances(e, scopes()) == [(None, {"item_no": "7", "bid_date": "2026-09-17"})]


def test_instance_defaults_fill_absent_or_none_only():
    e = {"unit": "cost_detail_block", "for_each": "item.cost_details",
         "key": "cost_detail[{it.name}]", "params": "{it}", "default_key": "{it.name}",
         "instance_defaults": {"LUMBER": {"header_price": 0}, "FUEL": {"header_price": 0}}}
    got = dict(R.instances(e, scopes()))
    assert got["cost_detail[LUMBER]"]["header_price"] == 0      # absent -> default
    assert got["cost_detail[FUEL]"]["header_price"] == 4        # present -> kept


def test_instances_never_alias_item_data():
    e = {"unit": "labor_block", "for_each": "item.labor", "params": "{it}"}
    (_, params), _ = R.instances(e, scopes())
    params["slot"] = "Z"
    assert ITEM["labor"][0]["slot"] == "A"


# ---- validation -------------------------------------------------------------

UNITS = {"item_header": {}, "takeoff_geometry": {}}


def test_validate_accepts_a_good_document():
    R.validate_recipes({"recipes": {"r": {"units": [{"unit": "item_header"}]}}}, UNITS)


def test_validate_rejects_a_non_mapping_entry():
    """`_check_entry`'s entry-is-a-mapping check backs both recipes.NAME[i]
    and a book sheet's units[j] -- this pins the recipes.NAME[i] side."""
    with pytest.raises(R.RecipeError, match=r"r\[0\].*mapping"):
        R.validate_recipes({"recipes": {"r": {"units": ["not-a-mapping"]}}}, UNITS)


def test_validate_rejects_an_unknown_unit():
    with pytest.raises(R.RecipeError, match=r"r\[0\].*nope"):
        R.validate_recipes({"recipes": {"r": {"units": [{"unit": "nope"}]}}}, UNITS)


def test_validate_rejects_an_unknown_entry_key():
    with pytest.raises(R.RecipeError, match="exec"):
        R.validate_recipes({"recipes": {"r": {"units": [{"unit": "item_header", "exec": "x"}]}}}, UNITS)


def test_validate_checks_variant_tables():
    doc = {"recipes": {"r": {"units": [{"unit": "takeoff", "variant_from": "item.takeoff.kind",
                                        "variants": "tv"}]}},
           "tv": {"geometry": "takeoff_geometry", "sub": "missing_unit"}}
    with pytest.raises(R.RecipeError, match="missing_unit"):
        R.validate_recipes(doc, UNITS)


def test_validate_checks_globals():
    doc = {"recipes": {}, "globals": {"p": {"export": "a.b", "scope": "sheet"}}}
    with pytest.raises(R.RecipeError, match="reserved"):
        R.validate_recipes(doc, UNITS)
    doc["globals"] = {"g": {"export": "a.b", "scope": "galaxy"}}
    with pytest.raises(R.RecipeError, match="scope"):
        R.validate_recipes(doc, UNITS)


def test_validate_allows_sheet_only_on_anchored_units():
    units = {"rate_table": {"anchor": {"col": "J", "row": 13}}, "item_header": {}}
    R.validate_recipes({"recipes": {"r": {"units": [{"unit": "rate_table", "sheet": "Rates"}]}}}, units)
    with pytest.raises(R.RecipeError, match="anchored"):
        R.validate_recipes({"recipes": {"r": {"units": [{"unit": "item_header", "sheet": "X"}]}}}, units)


def test_validate_rejects_a_recipe_level_position_key():
    """`position:` on a recipe is parsed but never acted on -- sheet order
    actually comes from the estimate config's item order (plus the cover,
    always first). Rather than let an author set something inert, refuse it
    by name at load."""
    doc = {"recipes": {"cover": {"sheet_name": "Cover", "position": 0,
                                  "units": [{"unit": "item_header"}]}}}
    with pytest.raises(R.RecipeError, match="position"):
        R.validate_recipes(doc, UNITS)


# ---- concat / unique (fieldbook phase 3b: the org-wide code list) ----------

def test_concat_splices_each_part_in_order():
    v = {"concat": [{"for_each": "item.labor", "as": "{it.slot}"}, ["C"], "D"]}
    assert R.resolve_value(v, scopes()) == ["A", "B", "C", "D"]


def test_concat_flattens_a_for_each_of_lists_one_level():
    cfg = {"items": [{"labor": [{"c": "1"}, {"c": "2"}]}, {"labor": [{"c": "3"}]}, {}]}
    v = {"concat": {"for_each": "config.items",
                    "as": {"for_each": "it.labor", "as": "{it.c}"}}}
    assert R.resolve_value(v, scopes(config=cfg)) == ["1", "2", "3"]


def test_unique_keeps_the_first_element_per_field_value_compared_as_text():
    cfg = {"org": [{"code": "02-100", "d": "org"}, {"code": 31, "d": "org"}],
           "tasks": [{"code": "02-100", "d": "task"}, {"code": "31", "d": "task"},
                     {"code": "02-900", "d": "task"}, {"d": "no code"}, {"d": "no code"}]}
    v = {"concat": [{"for_each": "config.org", "as": "{it}"},
                    {"for_each": "config.tasks", "as": "{it}"}],
         "unique": "code"}
    assert R.resolve_value(v, scopes(config=cfg)) == [
        {"code": "02-100", "d": "org"}, {"code": 31, "d": "org"},
        {"code": "02-900", "d": "task"}, {"d": "no code"}, {"d": "no code"}]


def test_unique_on_scalars_compares_the_element_itself():
    v = {"concat": [["a", "b"], ["b", "c", "a"]], "unique": True}
    assert R.resolve_value(v, scopes()) == ["a", "b", "c"]


def test_concat_of_missing_lists_is_empty():
    v = {"concat": [{"for_each": "config.absent", "as": "{it}"}], "unique": "code"}
    assert R.resolve_value(v, scopes()) == []


@pytest.mark.parametrize("bad, match", [
    ({"concat": "plain text"}, "concat"),
    ({"concat": [], "unique": ""}, "unique"),
    ({"concat": [], "unique": 3}, "unique"),
    ({"concat": [], "sort": "code"}, "sort"),
])
def test_a_malformed_concat_is_a_recipe_error(bad, match):
    with pytest.raises(R.RecipeError, match=match):
        R.resolve_value(bad, scopes())
