"""Work packages: schema shape and the cross-references jsonschema cannot express."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.estimate_spec import scaffold
from estimating_tools.estimate_spec.tests._fieldbook import example_spec, fieldbook_pack
from estimating_tools.estimate_spec.validate import validate_cross_references

PKG = {"name": "Hauling", "kind": "subcontract", "items": ["2"]}


def _spec(*packages, haul_package="Hauling"):
    spec = copy.deepcopy(example_spec())
    spec["work_packages"] = [copy.deepcopy(p) for p in (packages or (PKG,))]
    item = next(i for i in spec["items"] if i["item_no"] == "2")
    block = next(b for b in item["labor"] if b["slot"] == "02")
    block["lines"][0]["package"] = haul_package
    return spec


def _raises(spec, lead):
    with pytest.raises(ValueError) as e:
        validate_cross_references(spec)
    assert str(e.value).startswith(lead), str(e.value)


def test_a_packaged_spec_validates_against_the_fieldbook_schema():
    spec = _spec()
    spec["work_packages"][0].update(strategy="hybrid", selected="ARR", picks={"2": "ARR"},
                                    carry={"2": 100.0}, surcharge={"2": 5})
    spec["work_packages_quotes_dir"] = "quotes"
    spec["work_packages_spare_vendor_columns"] = 4
    next(b for i in spec["items"] if i["item_no"] == "2" for b in i["labor"])["carry"] = "self_perform"
    scaffold.validate_spec(spec, pack=fieldbook_pack())


def test_a_bad_package_kind_fails_the_schema():
    spec = _spec()
    spec["work_packages"][0]["kind"] = "lease"
    with pytest.raises(Exception):
        scaffold.validate_spec(spec, pack=fieldbook_pack())


def test_duplicate_package_name():
    _raises(_spec(PKG, PKG), "work_packages: duplicate package name 'Hauling'")


def test_package_item_not_in_spec():
    _raises(_spec({**PKG, "items": ["2", "99"]}), "work_packages[Hauling].items: item '99' is not in the spec")


def test_line_package_not_a_work_package():
    _raises(_spec(haul_package="Nope"), "items[2].labor[02].lines[0].package: 'Nope' is not a work package")


def test_line_package_does_not_list_item():
    _raises(_spec({**PKG, "items": ["3"]}),
            "items[2].labor[02].lines[0].package: package 'Hauling' does not list item '2'")


def _two_lines(pkg):
    spec = _spec(pkg)
    item = next(i for i in spec["items"] if i["item_no"] == "2")
    next(b for b in item["labor"] if b["slot"] == "02")["lines"].append(
        {"cost_type": "subcontract", "name": "Dump fees", "qty": 1, "uom": "LS",
         "unit_price": 500, "package": "Hauling"})
    return spec


def test_carry_keyed_by_item_or_by_line_validates():
    validate_cross_references(_spec({**PKG, "carry": {"2": 17.5}}))
    validate_cross_references(_two_lines({**PKG, "carry": {"2/Dump fees": 400,
                                                           "2/Haul, import + export": 17.5}}))


def test_carry_by_item_on_a_multi_line_item_names_the_lines():
    _raises(_two_lines({**PKG, "carry": {"2": 17.5}}),
            "work_packages[Hauling].carry: item '2' has several package lines; key it as "
            "'2/<line name>' (lines: Haul, import + export, Dump fees)")


def test_carry_naming_no_package_line():
    _raises(_spec({**PKG, "carry": {"2/Bedding rock": 1}}),
            "work_packages[Hauling].carry: line '2/Bedding rock' is not a package line")


@pytest.mark.parametrize("key", ["picks", "carry"])
def test_picks_and_carry_must_name_package_items(key):
    pkg = {**PKG, key: {"3": "ARR" if key == "picks" else 1}}
    _raises(_spec(pkg), f"work_packages[Hauling].{key}: item '3' is not in the package")


def test_no_packages_is_silent():
    validate_cross_references(example_spec())
