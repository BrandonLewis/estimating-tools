"""A small declaration in fieldbook's shape, grown one feature per task:
pack kinds aliased to contract kinds (``base``), then a tagged rates sheet,
the binding forms and the per-item sheets. Each function returns a fresh
document; ``full()`` is all of them."""
from __future__ import annotations

import copy

_BASE = {
    "schema": 1,
    "pack": {"name": "forms", "version": "1", "contract": "1"},
    "kind": "recipe",
    "prototypes": {"task": "t.task", "crew": "t.crew", "line": "t.line"},
    "kinds": {"TASK": "ACTIVITY", "CREW": "RESOURCE", "LINE": "RESOURCE"},
    "sheets": {
        "items": {
            "tab": "1 - MOBILIZATION", "role": "blocks", "first_row": 1,
            "columns": {"A": "Code / resource", "B": "Qty", "C": "Unit", "D": "Count",
                        "E": "Days", "G": "Rate", "H": "Type", "I": "Source", "J": "Vendor",
                        "Z": "Time unit"},
            "tags": {"kind": "Q", "parent": {"column": "R", "derived": ["RESOURCE", "END"]},
                     "id": "W", "v": "X", "ref": "Y"},
            "rows": ["ITEM", "HEAD", "SUBTOTAL"],
            "not_shown": ["STEP", "ELEMENT_QTY"],
            "blocks": {"task": {"kind": "ACTIVITY", "within": ["ITEM"],
                                "children": ["resources"]},
                       "resources": {"marker": {"open": "ACTIVITY", "close": "END"},
                                     "row": "RESOURCE"}},
            "markers": {"END": {"cue": {"column": "A",
                                        "text": "insert new lines above this row"}}},
            "fields": {"TASK": {"name": "B"},
                       "CREW": {"name": "A", "quantity": "D", "time_value": "E",
                                "time_unit": "Z", "component_type": "H"},
                       "LINE": {"name": "A", "quantity": "B", "unit": "C", "unit_cost": "G",
                                "component_type": "H"}},
        },
    },
}


def base() -> dict:
    """Pack kinds: TASK is an ACTIVITY, CREW and LINE are RESOURCEs."""
    return copy.deepcopy(_BASE)


_RATES = {
    "tab": "Rates", "role": "rates", "first_row": 1,
    "columns": {"A": "Resource", "B": "Kind", "G": "Rate"},
    "tags": {"kind": "I", "ref": "J"},
    "columns_by_key": {"name": "A", "kind": "B", "rate": "G"},
    "sections": {"labor": "Labor", "equipment": "Equipment"},
    "local_suffix": " (local)",
}


def with_rates(doc: dict | None = None) -> dict:
    """``doc`` (default ``base()``) with fieldbook's tagged Rates sheet."""
    doc = copy.deepcopy(doc) if doc is not None else base()
    doc["sheets"]["rates"] = copy.deepcopy(_RATES)
    return doc


def with_bindings(doc: dict | None = None) -> dict:
    """``doc`` (default ``with_rates()``) binding fieldbook's joined,
    rate-picked and named fields, with its Type spellings."""
    doc = copy.deepcopy(doc) if doc is not None else with_rates()
    items = doc["sheets"]["items"]
    items["fields"]["TASK"].update(
        description={"rows": "NOTE", "column": "A", "join": "\n"},
        hours_per_shift={"by_name": "est.shift_hours"})
    items["fields"]["CREW"].update(component_type={"from_rate": "kind"},
                                   unit_cost={"from_rate": "rate"})
    items["fields"]["LINE"].update(description={"cells": ["I", "J"], "join": " · "})
    items["spellings"] = {"component_type": {"Subcontract": "subcontractor"}}
    return doc


def with_each(doc: dict | None = None) -> dict:
    """``doc`` (default ``with_bindings()``) with one item sheet per bid
    item and the task row's chain cell derived."""
    doc = copy.deepcopy(doc) if doc is not None else with_bindings()
    items = doc["sheets"]["items"]
    del items["tab"]
    items["each"] = "ITEM"
    items["tags"]["parent"]["derived"] = ["ACTIVITY", "RESOURCE", "END"]
    return doc


def full() -> dict:
    """Every feature: fieldbook's shape."""
    return with_each()
