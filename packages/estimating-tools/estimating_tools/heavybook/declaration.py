"""HeavyBook's declaration (engine spec, Layer 2), generated from
``columns.py`` and the letter-bearing tables below -- the source of truth for
which column holds each bound field, export value and formula, which cell a
marker's cue sits in and what text a writer puts on a row; the reader takes
them from the declaration (``exchange.reader.fields``, ``exchange.reader.scan``)
-- so the shipped ``pack.yaml`` and the stamped declaration cannot drift from the code.
``generate(tabs)`` takes the styled tab titles for a built book; the shipped
file uses the defaults. ``generate(derived=False)`` is the declaration of a
book whose owner tags are stored constants (layout 2: 0.1.95 and 0.1.96,
upgraded in memory by ``legacy.upgrade``): no tag is derived, and the Crews
sheet has no crew-row helper column."""
from __future__ import annotations

import json

from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.declaration import SCHEMA_VERSION
from estimating_tools.heavybook import FORMAT_NAME, FORMAT_VERSION
from estimating_tools.heavybook import columns as C
from estimating_tools.heavybook.columns import BF, CK, CR, CW, RT
from estimating_tools.heavybook.layout import (
    DERIVED, FIRST_ROW, HEADER_ROW, NAVIGATOR_STATUSES, TEMPLATE_NAMES)
from estimating_tools.heavybook.sheets.cost_report import END_CUE
from estimating_tools.heavybook.sheets.crews import CREW_END_CUE, LIBRARY_BANNER
from estimating_tools.heavybook.sheets.rates import _TITLES

__all__ = ["DEFAULT_TABS", "DERIVED", "as_json", "dumps", "generate"]

DEFAULT_TABS = {"cost_report": "Cost Report", "crews": "Crews", "bid_form": "Bid Form",
                "rates": "Rates", "checks": "Checks"}

#: The input cells by (sheet, kind): ``(letter, field)`` for each of the
#: kind's writable fields (``contract.FIELDS``), in the contract's order.
#: These are exactly the cells the writer styles ``input_*``
#: (``sheets/cost_report.py``, ``sheets/crews.py``, ``sheets/bid_form.py``).
#: ACTIVITY ``duration_shifts`` is an input only on an activity without
#: steps (the contract's ``stepped`` qualifier).
_INPUTS = {
    ("cost_report", "ITEM"): ((CR.QTY, "quantity_override"),
                              (CR.UCOST, "estimated_unit_price")),
    ("cost_report", "ELEMENT_QTY"): ((CR.QTY, "override_value"),),
    ("cost_report", "ACTIVITY"): ((CR.DESC, "name"),
                                  (CR.PROD, "production_rate"),
                                  (CR.PUNIT, "production_unit"),
                                  (CR.HPS, "hours_per_shift"),
                                  (CR.CFACT, "crew_factor"),
                                  (CR.SHIFTS, "duration_shifts"),
                                  (CR.COUNT, "count")),
    ("cost_report", "STEP"): ((CR.DESC, "name"),
                              (CR.QTY, "duration"),
                              (CR.UNIT, "duration_unit")),
    ("cost_report", "RESOURCE"): ((CR.DESC, "name"),
                                  (CR.QTY, "quantity"),
                                  (CR.UNIT, "unit"),
                                  (CR.UCOST, "unit_cost"),
                                  (CR.PROD, "time_value"),
                                  (CR.PUNIT, "time_unit"),
                                  (CR.TYPE, "component_type"),
                                  (CR.BASIS, "labor_cost_basis"),
                                  (CR.BURD, "burden_percentage"),
                                  (CR.BINC, "includes_burden")),
    ("crews", "MEMBER"): ((CW.CODE, "classification"),
                          (CW.COUNT, "count"),
                          (CW.OVERRIDE, "hourly_rate_override")),
    ("bid_form", "ITEM_BID"): ((BF.SCOPE, "scope"),
                               (BF.OVERRIDE, "bid_unit_price_override")),
}

#: Cells the writer shows as export values (no apply op writes them) that
#: the book's formulas read, by (sheet, kind): ``(letter, baseline
#: attribute)``. The crew's hours/shift and factor feed every crew-priced
#: activity's labour and man-hours; the bid quantity, the item's bid unit
#: price and total (on the Bid Form, and hidden on the item's Cost Report
#: row); the derived quantity, the element quantity's effective figure; a
#: member's rate as of export, its library rate when the rate is not on the
#: Rates sheet.
_EXPORT_VALUES = {
    ("crews", "CREW"): ((CW.HPS, "hours_per_shift"), (CW.CFACT, "crew_factor")),
    # A member's rate as of export: its library-rate formula falls back to it.
    ("crews", "MEMBER"): ((CW.EXPORT, "effective_hourly_rate"),),
    ("bid_form", "ITEM_BID"): ((BF.QTY, "schedule_quantity"),),
    ("cost_report", "ELEMENT_QTY"): ((CR.UCOST, "derived"),),
    # The item's bid quantity, hidden on its Cost Report row: its effective
    # quantity (AG) reads it, and so the unit price and the Recap.
    ("cost_report", "ITEM"): ((CR.H1, "schedule_quantity"),),
}

_SPLIT = tuple(col for _kind, col in CR.SPLIT)

#: The cells the writer fills with a formula, by (sheet, kind). Every Cost
#: Report row also carries the activity-row helper (``CR.ACT``), an included
#: item its ``H4``, and a stepped activity its Shifts (``_formulas``).
_FORMULAS = {
    ("cost_report", "ITEM"): _SPLIT + (CR.TOTAL, CR.H2, CR.H3),
    ("cost_report", "ELEMENT_QTY"): (CR.H2,),
    ("cost_report", "ACTIVITY"): (CR.MH, CR.LAB) + _SPLIT[1:] + (CR.TOTAL, CR.MULT),
    ("cost_report", "RESOURCE"): (CR.MH,) + _SPLIT + (CR.TOTAL, CR.H1, CR.H2),
    ("crews", "CREW"): (CW.HEADCOUNT, CW.RATE),
    ("crews", "MEMBER"): (CW.LIBRATE, CW.EFFECTIVE, CW.EXTENDED),
    ("bid_form", "ITEM_BID"): (BF.PRICE, BF.TOTAL, BF.COST, BF.PRICED, BF.PCOST),
    ("bid_form", "BID_TOTAL"): (BF.TOTAL,),
}

#: Bid Form figures that are formulas (the rest are as of export).
_FORMULA_FIGURES = ("direct_cost", "markup_total", "bid_factor", "excluded_cost")

#: Per sheet and marker kind: the cue cell and the cue it holds (what the
#: writers put there: ``sheets/cost_report.py``, ``sheets/crews.py``). A
#: marker's visible cells are blank except that one, and only while it
#: holds its cue; the reader takes these from the declaration.
_CUES = {
    "cost_report": {"STEPS": None, "START": None, "END": (CR.DESC, END_CUE)},
    "crews": {"NOTE": (CW.NAME, LIBRARY_BANNER), "CREW_END": (CW.NAME, CREW_END_CUE)},
}

#: Fixed text a row's writer puts in a visible cell (``cost_report._step``'s
#: tag): not typed, so it doesn't make a new row touched.
_WRITTEN = {("cost_report", "STEP"): {CR.CODE: "step"}}


def _columns(cols) -> dict:
    return {c.letter: c.heading for c in cols if not c.hidden}


def _fields(sheet: str) -> dict:
    return {kind: {name: letter for letter, name in inputs}
            for (s, kind), inputs in _INPUTS.items() if s == sheet}


def _export_values(sheet: str) -> dict:
    return {kind: {letter: attr for letter, attr in rows}
            for (s, kind), rows in _EXPORT_VALUES.items() if s == sheet}


def _formulas(sheet: str, *, crew_helper: bool = True) -> dict:
    out = {kind: list(letters) for (s, kind), letters in _FORMULAS.items() if s == sheet}
    if sheet == "cost_report":
        out["*"] = [CR.ACT]
        out["ITEM.included"] = [CR.H4]
        out["ACTIVITY.stepped"] = [CR.SHIFTS]
    if sheet == "crews" and crew_helper:
        out["*"] = [CW.OWNER]
    return out


def _parent(sheet: str, column: str, *, derived: bool) -> dict:
    """The parent tag: derived for the sheet's block rows and markers
    (``layout.DERIVED``), or stored everywhere (a layout-2 book)."""
    return {"column": column, "derived": list(DERIVED[sheet]) if derived else []}


def _markers(sheet: str) -> dict:
    out = {}
    for kind, cue in _CUES[sheet].items():
        out[kind] = {"cue": {"column": cue[0], "text": cue[1]}} if cue else {}
    return out


def _written(sheet: str) -> dict:
    return {kind: dict(text) for (s, kind), text in _WRITTEN.items() if s == sheet}


def generate(tabs: dict | None = None, *, derived: bool = True) -> dict:
    """The declaration of a book built by this code (``derived``: its owner
    tags are formulas and its Crews sheet carries the crew-row helper), or
    with ``derived=False`` of a layout-2 book, whose cells hold stored tags
    and no helper column (``legacy.upgrade``)."""
    tabs = {**DEFAULT_TABS, **(tabs or {})}
    crew_helper = derived
    crew_tags = {"kind": CW.KIND, "id": CW.ID, "v": CW.V,
                 "parent": _parent("crews", CW.CREW, derived=derived), "ref": CW.RATE_ID}
    if crew_helper:
        crew_tags["owner_row"] = CW.OWNER
    return {
        "schema": SCHEMA_VERSION,
        "pack": {"name": FORMAT_NAME, "version": FORMAT_VERSION, "contract": "1"},
        "kind": "code",
        "stamp": {"name": exchange_stamp.NAME, "sheet": exchange_stamp.SHEET,
                  "cell": exchange_stamp.CELL, "property": exchange_stamp.PROPERTY},
        "prototypes": dict(TEMPLATE_NAMES),
        "navigator": {"templates": dict(TEMPLATE_NAMES),
                      "statuses": {k: list(v) for k, v in NAVIGATOR_STATUSES.items()},
                      "tables": {"checks": {"sheet": tabs["checks"], "name": "hc.checks",
                                            "columns": {"kind": CK.KIND, "code": CK.CODE,
                                                        "measure": CK.MEASURE,
                                                        "status": CK.STATUS}}},
                      "cells": {"bid_totals": "hc.bid_totals"}},
        "sheets": {
            "cost_report": {
                "tab": tabs["cost_report"], "role": "blocks",
                "first_row": FIRST_ROW, "header_row": HEADER_ROW,
                "columns": _columns(C.COST_REPORT),
                "tags": {"kind": CR.KIND, "id": CR.ID, "v": CR.V,
                         "parent": _parent("cost_report", CR.PARENT, derived=derived),
                         "key": CR.KEY, "ref": CR.REF, "owner_row": CR.ACT},
                "rows": ["ITEM", "ELEMENT_QTY", "GROUP"],
                "blocks": {
                    "activity": {"kind": "ACTIVITY", "recursive": True,
                                 "within": ["ITEM", "GROUP"],
                                 "children": ["steps", "resources"]},
                    "steps": {"marker": {"open": "STEPS", "close": "START"}, "row": "STEP",
                              "optional": True},
                    "resources": {"marker": {"open": "START", "close": "END"},
                                  "row": "RESOURCE"},
                },
                "markers": _markers("cost_report"),
                "fields": _fields("cost_report"),
                "export_values": _export_values("cost_report"),
                "formulas": _formulas("cost_report"),
                "written": _written("cost_report"),
            },
            "crews": {
                "tab": tabs["crews"], "role": "blocks",
                "first_row": FIRST_ROW, "header_row": HEADER_ROW,
                "columns": _columns(C.CREWS),
                "tags": crew_tags,
                "blocks": {
                    "crew": {"kind": "CREW", "children": ["members"]},
                    "members": {"marker": {"open": "CREW", "close": "CREW_END"},
                                "row": "MEMBER", "banner": "NOTE"},
                },
                "markers": _markers("crews"),
                "fields": _fields("crews"),
                "export_values": _export_values("crews"),
                "formulas": _formulas("crews", crew_helper=crew_helper),
            },
            "bid_form": {
                "tab": tabs["bid_form"], "role": "flat",
                # the named rows sit above the header; items start at BF.FIRST_ROW
                "first_row": 1, "header_row": BF.HEADER_ROW,
                "columns": _columns(C.BID_FORM),
                "tags": {"kind": BF.KIND, "id": BF.ID, "v": BF.V, "name": BF.INPUT},
                "rows": ["SECTION", "ITEM_BID", "GROUP", "BID_TOTAL"],
                "fields": _fields("bid_form"),
                "export_values": _export_values("bid_form"),
                "formulas": _formulas("bid_form"),
                "named_rows": {
                    "name_column": BF.INPUT, "value_column": BF.VALUE,
                    "rows": {name: {"kind": ("ESTIMATE" if name == "markup_percentage"
                                             else "BID_INPUT" if name in BF.INPUTS
                                             else "BID_FIGURE"),
                                    **({"input": True} if name in BF.INPUTS else {}),
                                    **({"formula": True} if name in _FORMULA_FIGURES else {})}
                             for name in BF.ROWS},
                },
            },
            "rates": {
                "tab": tabs["rates"], "role": "rates",
                "columns_by_key": {"id": RT.ID, "name": RT.NAME, "unit": RT.UNIT, "rate": RT.RATE},
                "sections": dict(_TITLES),
            },
        },
    }


def dumps(doc: dict) -> str:
    """The shipped file's text: YAML in key order, a header comment first."""
    import yaml

    head = ("# HeavyBook's exchange declaration (engine spec, Layer 2). GENERATED by\n"
            "# heavybook/declaration.py from columns.py and its own tables;\n"
            "# regenerate with UPDATE_GOLDEN=1 pytest heavybook/tests/test_declaration.py\n")
    return head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def as_json(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))
