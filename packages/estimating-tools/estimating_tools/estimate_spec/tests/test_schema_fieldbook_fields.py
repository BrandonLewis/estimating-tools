"""Fieldbook phase 1: optional spec fields every pack may use."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.scaffold import validate_spec
from estimating_tools.estimate_spec.tests._packs import LEGACY_DIR, legacy_example, patched_pack

ALT_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "alt"
ALT_SAMPLE = ALT_DIR / "examples" / "sample.estimate.yaml"


@pytest.fixture(scope="module")
def legacy():
    return fp.load_pack(LEGACY_DIR)


@pytest.fixture(scope="module")
def opted(tmp_path_factory):
    """legacy_demo with `markup_by_type: true` in its vocabulary -- the opt-in
    a pack that lays out its own markup sheet declares."""
    def vocabulary(doc):
        doc["markup_by_type"] = True

    return patched_pack(tmp_path_factory.mktemp("opted"), vocabulary=vocabulary)


_OBJECT_MARKUP = {"overhead": {"labor": 0.12, "equipment": 0.10,
                               "material": 0.05, "subcontract": 0.03},
                  "profit": {"labor": 0.12},
                  "bond_pct": 0.012}


def _full():
    """The legacy example with every new field set, consistently -- except
    object-form markup, which only an opted-in pack accepts (`_with_object_markup`)."""
    spec = legacy_example()
    spec["shift_hours"] = 10
    spec["rate_table"][0].update(base=60.0, burden_pct=0.25, fringe=20.0)    # 60*1.25+20 = 95
    spec["rate_table"].append({"trade": "Excavator, 320 class", "rate": 145.0,
                               "kind": "equipment", "includes_operator": False})
    item = spec["items"][1]
    item["unbalance"] = -1000
    block = item["labor"][0]
    block["notes"] = ["Trench to 6 ft max."]
    block["lines"] = [
        {"cost_type": "material", "name": "8-in DI pipe", "qty": 640, "uom": "LF",
         "unit_price": 42, "source": "quote", "vendor": "Ferguson"},
        {"cost_type": "subcontract", "name": "Haul", "qty": 460, "uom": "CY", "unit_price": 18}]
    item["cost_details"][0]["lines"][0].update(source="plug", vendor="")
    return spec


def _with_object_markup():
    spec = _full()
    spec["markup"] = copy.deepcopy(_OBJECT_MARKUP)
    return spec


def test_every_new_field_validates(legacy):
    validate_spec(_full(), pack=legacy)


def test_object_markup_validates_on_a_pack_that_opts_in(opted):
    validate_spec(_with_object_markup(), pack=opted)


def test_object_markup_is_refused_by_a_pack_that_does_not_opt_in(legacy):
    with pytest.raises(ValueError, match="schema violation"):
        validate_spec(_with_object_markup(), pack=legacy)


def test_a_plain_markup_still_validates_on_a_pack_that_opts_in(opted):
    validate_spec(_full(), pack=opted)


def test_a_non_bool_markup_by_type_is_refused_at_load(tmp_path):
    def vocabulary(doc):
        doc["markup_by_type"] = "yes"

    with pytest.raises(fp.FormatPackError, match="markup_by_type"):
        patched_pack(tmp_path, vocabulary=vocabulary)


def test_generate_refuses_object_markup_on_a_pack_that_does_not_opt_in(legacy):
    from estimating_tools.estimate_spec import recipe as R
    from estimating_tools.estimate_spec.build import generate

    spec = legacy_example()
    spec["markup"] = copy.deepcopy(_OBJECT_MARKUP)
    with pytest.raises(R.RecipeError, match="markup by cost type needs a pack that opts in"):
        generate(spec, pack=legacy)


def test_the_legacy_example_still_validates_untouched(legacy):
    validate_spec(legacy_example(), pack=legacy)


def _set(path, value):
    def edit(spec):
        node = spec
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    return edit


def _vehicle_kind(spec):
    """Only the kind enum should refuse this: drop includes_operator too, so
    the if/then/else equipment branch has nothing else to object to."""
    row = spec["rate_table"][-1]
    row["kind"] = "vehicle"
    del row["includes_operator"]


def _equipment_wage_breakdown(spec):
    """Only the then-branch (equipment forbids wage fields) should refuse
    this: pair base with burden_pct so dependentRequired is satisfied too."""
    row = spec["rate_table"][-1]
    row["base"] = 100.0
    row["burden_pct"] = 0.3


@pytest.mark.parametrize("edit", [
    _set(["items", 1, "labor", 0, "lines", 0, "cost_type"], "labor"),
    _set(["items", 1, "labor", 0, "lines", 0, "source"], "maybe"),
    _vehicle_kind,
    _equipment_wage_breakdown,
    _set(["rate_table", 1, "includes_operator"], True),       # labor row with an equipment flag
    _set(["shift_hours"], 0),
])
def test_bad_values_are_refused(legacy, edit):
    spec = _full()
    edit(spec)
    with pytest.raises(ValueError, match="schema violation"):
        validate_spec(spec, pack=legacy)


@pytest.mark.parametrize("edit", [
    _set(["markup", "overhead", "fuel"], 0.1),
    _set(["markup", "overhead", "labor"], -0.01),              # a discount goes in unbalance, not here
    _set(["markup", "bond_pct"], 1.0),
])
def test_bad_object_markup_is_refused_even_on_a_pack_that_opts_in(opted, edit):
    spec = _with_object_markup()
    edit(spec)
    with pytest.raises(ValueError, match="schema violation"):
        validate_spec(spec, pack=opted)


def test_a_fringe_without_a_base_is_refused(legacy):
    spec = _full()
    spec["rate_table"][1]["fringe"] = 5.0
    with pytest.raises(ValueError, match="schema violation"):
        validate_spec(spec, pack=legacy)


def test_item_rules_can_require_a_cost_code_on_every_labor_block(tmp_path):
    """Amendment 3: fieldbook enforces cost codes through item_rules."""
    def vocabulary(doc):
        doc.setdefault("item_rules", []).append(
            {"properties": {"labor": {"items": {"required": ["cost_code"]}}}})

    pack = patched_pack(tmp_path, vocabulary=vocabulary)
    spec = legacy_example()
    for item in spec["items"]:
        for block in item.get("labor") or []:
            block["cost_code"] = "01-000"
    validate_spec(copy.deepcopy(spec), pack=pack)
    del spec["items"][1]["labor"][0]["cost_code"]
    with pytest.raises(ValueError, match="cost_code"):
        validate_spec(spec, pack=pack)


def test_summarize_refuses_markup_by_cost_type_by_name():
    from estimating_tools.estimate_spec.summarize import _markup
    with pytest.raises(ValueError, match="markup by cost type"):
        _markup({"overhead": {"labor": 0.1}}, 100.0)


def test_cli_summarize_reports_markup_by_type_cleanly(tmp_path, capsys):
    """_markup raises FormulaError (not a bare ValueError) so cmd_summarize's
    narrow except catches it and prints a clean message, not a traceback."""
    from estimating_tools.estimate_spec.cli import main

    spec = yaml.safe_load(ALT_SAMPLE.read_text(encoding="utf-8"))
    spec["markup"] = {"overhead": {"labor": 0.1}}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec), encoding="utf-8")

    rc = main(["summarize", str(spec_path), "--format", str(ALT_DIR)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "markup by cost type" in out
    assert "Traceback" not in out


def test_a_breakdown_that_does_not_reproduce_the_rate_is_refused(legacy):
    spec = _full()
    spec["rate_table"][0]["rate"] = 90.0          # breakdown says 95.00
    with pytest.raises(ValueError, match=r"rate_table\[0\].*95\.00.*90\.00"):
        validate_spec(spec, pack=legacy)


def test_a_breakdown_within_a_cent_is_accepted(legacy):
    spec = _full()
    spec["rate_table"][0].update(rate=81.89, base=48.10, burden_pct=0.32, fringe=18.40)  # 81.892
    validate_spec(spec, pack=legacy)


def test_bm_generate_refuses_a_rate_breakdown_that_does_not_reproduce_the_rate(legacy):
    from estimating_tools.estimate_spec.build import generate

    spec = _full()
    spec["rate_table"][0]["rate"] = 90.0          # breakdown says 95.00
    with pytest.raises(ValueError, match=r"rate_table\[0\].*95\.00.*90\.00"):
        generate(spec, pack=legacy)
