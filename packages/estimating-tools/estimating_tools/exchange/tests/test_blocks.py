from __future__ import annotations

import copy

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.reader.blocks import Blocks
from estimating_tools.exchange.tests.test_declaration import MINIMAL


def _blocks(key):
    return Blocks(D.load(MINIMAL).sheets[key])


def _chain(optional):
    """A cost report whose activity has three chained children a, b, c
    (markers OA -> OB -> OC -> END), the named ones optional."""
    doc = copy.deepcopy(MINIMAL)
    cr = doc["sheets"]["cost_report"]
    cr["blocks"] = {
        "activity": {"kind": "ACTIVITY", "recursive": True, "within": ["ITEM", "GROUP"],
                     "children": ["a", "b", "c"]},
        "a": {"marker": {"open": "OA", "close": "OB"}, "row": "STEP", "optional": "a" in optional},
        "b": {"marker": {"open": "OB", "close": "OC"}, "row": "RESOURCE",
              "optional": "b" in optional},
        "c": {"marker": {"open": "OC", "close": "END"}, "row": "MEMBER", "optional": "c" in optional},
    }
    cr["markers"] = {"OA": {}, "OB": {}, "OC": {}, "END": {}}
    cr["formulas"] = {"*": ["AJ"], "ITEM": ["R"], "ITEM.included": ["AI"]}
    return Blocks(D.load(doc).sheets["cost_report"])


def test_cost_report_zones_and_markers():
    b = _blocks("cost_report")
    assert b.owner.kind == "ACTIVITY" and b.container == "ITEM" and b.within == ("ITEM", "GROUP")
    assert b.zones == ("head", "steps", "resources")
    assert b.opens("STEPS").name == "steps" and b.opens("START").name == "resources"
    assert b.closes("END").name == "resources" and b.closes("START") is None
    assert b.allowed_zones("STEPS") == ("head",)
    assert b.allowed_zones("START") == ("head", "steps")      # steps is optional
    assert b.allowed_zones("END") == ("resources",)
    assert b.block_of_row("STEP").name == "steps" and b.block_of_row("ELEMENT_QTY") is None
    assert b.is_marker("END") and not b.is_marker("ACTIVITY") and b.last.close == "END"
    assert b.opened_by_owner is None
    assert b.optional_head_rows == ("STEP",)                  # may be typed before its marker


def test_crews_block_is_opened_by_its_owner_row():
    b = _blocks("crews")
    assert b.owner.kind == "CREW" and b.container is None and b.within == ()
    assert b.zones == ("head", "members") and b.opened_by_owner.name == "members"
    assert b.closes("CREW_END").name == "members" and b.banners == ("NOTE",)
    assert b.allowed_zones("CREW_END") == ("members",)


@pytest.mark.parametrize("optional, zones", [
    # An open marker may follow ``head`` and every optional child before its
    # block; a required child between resets the start to its own zone.
    ("ac", {"OA": ("head",), "OB": ("head", "a"), "OC": ("b",), "END": ("c",)}),
    ("b", {"OA": ("head",), "OB": ("a",), "OC": ("a", "b"), "END": ("c",)}),
    ("a", {"OA": ("head",), "OB": ("head", "a"), "OC": ("b",), "END": ("c",)}),
])
def test_allowed_zones_skip_only_optional_children(optional, zones):
    b = _chain(optional)
    assert b.zones == ("head", "a", "b", "c") and b.last.name == "c"
    assert {m: b.allowed_zones(m) for m in zones} == zones
    assert b.closes("END").name == "c" and b.closes("OB") is None   # OB opens b


def test_rows_of_kind_map_to_the_contract_names():
    b = _blocks("cost_report")
    assert b.rows_named("STEP") == "steps" and b.rows_named("RESOURCE") == "resources"
    assert _blocks("crews").rows_named("MEMBER") == "members"
