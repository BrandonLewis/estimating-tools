from __future__ import annotations

import copy
import json

import pytest

from estimating_tools.exchange import declaration as D

#: Marks a key to delete in a document edit.
DELETE = object()

MINIMAL = {
    "schema": 1,
    "pack": {"name": "demo", "version": "1", "contract": "1"},
    "kind": "code",
    "prototypes": {"activity": "tpl.activity", "step": "tpl.step", "resource": "tpl.resource",
                   "member": "tpl.member"},
    "sheets": {
        "cost_report": {
            "tab": "Cost Report", "role": "blocks", "first_row": 5, "header_row": 4,
            "columns": {"A": "Code", "B": "Description", "C": "Quantity", "D": "Unit",
                        "E": "Unit cost"},
            "tags": {"kind": "W", "id": "X", "v": "Y", "parent": "Z", "key": "AD", "ref": "AE",
                     "owner_row": "AJ"},
            "rows": ["ITEM", "ELEMENT_QTY", "GROUP"],
            "blocks": {
                "activity": {"kind": "ACTIVITY", "recursive": True, "within": ["ITEM", "GROUP"],
                             "children": ["steps", "resources"]},
                "steps": {"marker": {"open": "STEPS", "close": "START"}, "row": "STEP",
                          "optional": True},
                "resources": {"marker": {"open": "START", "close": "END"}, "row": "RESOURCE"},
            },
            "markers": {"STEPS": {}, "START": {},
                        "END": {"cue": {"column": "B", "text": "insert lines above"}}},
            "fields": {"ITEM": {"estimated_unit_price": "E"},
                       "ACTIVITY": {"name": "B"},
                       "STEP": {"name": "B", "duration": "C", "duration_unit": "D"},
                       "RESOURCE": {"name": "B", "quantity": "C", "unit_cost": "E",
                                    "component_type": "D"}},
            "formulas": {"*": ["AJ"], "ITEM": ["R"], "ITEM.included": ["AI"],
                         "ACTIVITY.stepped": ["J"]},
        },
        "crews": {
            "tab": "Crews", "role": "blocks", "first_row": 5, "header_row": 4,
            "columns": {"A": "Code / class", "B": "Name", "C": "Count", "E": "Rate override"},
            "tags": {"kind": "K", "id": "L", "v": "M", "parent": "N"},
            "blocks": {"crew": {"kind": "CREW", "children": ["members"]},
                       "members": {"marker": {"open": "CREW", "close": "CREW_END"},
                                   "row": "MEMBER", "banner": "NOTE"}},
            "markers": {"CREW_END": {"cue": {"column": "B", "text": "insert members above"}},
                        "NOTE": {"cue": {"column": "B", "text": "Library crew"}}},
            "fields": {"MEMBER": {"classification": "A", "count": "C",
                                  "hourly_rate_override": "E"}},
        },
        "bid_form": {
            "tab": "Bid Form", "role": "flat", "first_row": 1, "header_row": 12,
            "columns": {"A": "Item", "C": "Schedule", "F": "Scope", "G": "Price override"},
            "tags": {"kind": "J", "id": "K", "v": "L", "name": "T"},
            "rows": ["SECTION", "ITEM_BID", "GROUP", "BID_TOTAL"],
            "fields": {"ITEM_BID": {"scope": "F", "bid_unit_price_override": "G"}},
            "named_rows": {"name_column": "T", "value_column": "C",
                           "rows": {"markup_percentage": {"kind": "ESTIMATE", "input": True},
                                    "markup_amount": {"kind": "BID_INPUT", "input": True},
                                    "direct_cost": {"kind": "BID_FIGURE", "formula": True}}},
        },
        "rates": {"tab": "Rates", "role": "rates",
                  "columns_by_key": {"id": "A", "name": "B", "unit": "C", "rate": "D"},
                  "sections": {"labor": "Labor rates", "equipment": "Equipment rates",
                               "material": "Material costs"}},
    },
}


def _bad(path, value):
    doc = copy.deepcopy(MINIMAL)
    node = doc
    for key in path[:-1]:
        node = node[key]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


def test_the_minimal_declaration_loads():
    decl = D.load(MINIMAL)
    assert decl.pack.name == "demo" and decl.schema == 1
    assert decl.sheets["cost_report"].tab == "Cost Report"
    assert decl.visible("cost_report") == ("A", "B", "C", "D", "E")
    assert decl.sheets["cost_report"].blocks["steps"].optional is True
    assert decl.size() < 32767


def test_row_kinds_match_heavybooks_shape():
    kinds = D.load(MINIMAL).row_kinds()
    assert kinds["cost_report"]["kind_cell"] == "W"
    assert kinds["cost_report"]["kinds"]["ELEMENT_QTY"] == {"id": "X", "key": "AD", "v": "Y"}
    assert kinds["cost_report"]["kinds"]["START"] == {"parent": "Z"}
    assert kinds["cost_report"]["kinds"]["GROUP"] == {}
    assert kinds["crews"]["kinds"]["MEMBER"] == {"id": "L", "parent": "N"}
    assert kinds["crews"]["kinds"]["NOTE"] == {"parent": "N"}
    assert kinds["bid_form"]["kinds"]["ESTIMATE"] == {"id": "K", "v": "L", "name": "T"}
    assert kinds["bid_form"]["kinds"]["BID_FIGURE"] == {"name": "T"}
    assert "rates" not in kinds


@pytest.mark.parametrize("path, value, says", [
    (("schema",), 2, "schema 2"),
    (("sheets", "cost_report", "fields", "ITEM", "colour"), "F", "ITEM.colour"),
    (("sheets", "cost_report", "fields", "ITEM", "quantity"), "C", "not writable"),
    (("sheets", "cost_report", "fields", "RESOURCE", "unit_cost"), "C", "column C twice"),
    (("sheets", "cost_report", "fields", "RESOURCE", "unit_cost"), "X", "tag column"),
    (("sheets", "cost_report", "tags", "key"), DELETE, "ELEMENT_QTY needs a key tag"),
    (("sheets", "cost_report", "tags", "parent"),
     {"column": "Z", "derived": ["ACTIVITY"]}, "ACTIVITY opens a recursive block"),
    (("prototypes", "step"), DELETE, "no prototype for STEP"),
    (("sheets", "cost_report", "blocks", "activity", "children"), ["steps", "lines"], "lines"),
    (("sheets", "cost_report", "blocks", "resources", "marker"), {"open": "START", "close": "FIN"},
     "FIN"),
    (("sheets", "cost_report", "markers", "END", "cue", "column"), "W", "not visible"),
    (("sheets", "bid_form", "tags", "name"), DELETE, "named rows need a name tag"),
    (("sheets", "cost_report", "formulas", "ITEM.blue"), ["R"], "blue"),
    (("sheets", "cost_report", "tags", "kind"), DELETE, "kind"),
    # Fields, formulas, export values and written text bind only kinds on the
    # sheet; a field sits on a visible column.
    (("sheets", "cost_report", "fields", "MEMBER"), {"classification": "A"},
     r"fields\.MEMBER: MEMBER is not a row kind of this sheet"),
    (("sheets", "cost_report", "formulas", "CREW"), ["R"],
     r"formulas\.CREW: CREW is not a row kind of this sheet"),
    (("sheets", "cost_report", "export_values"), {"MEMBER": {"E": "count"}},
     r"export_values\.MEMBER: MEMBER is not a row kind of this sheet"),
    (("sheets", "cost_report", "written"), {"CREW": {"A": "crew"}},
     r"written\.CREW: CREW is not a row kind of this sheet"),
    (("sheets", "cost_report", "fields", "ITEM", "estimated_unit_price"), "AB",
     r"fields\.ITEM\.estimated_unit_price: AB is not a visible column"),
    # Structural tag checks: markers name their owner, named rows are found
    # by the name tag, tags are hidden and share no column.
    (("sheets", "bid_form", "markers"), {"NOTE": {}}, r"bid_form\.tags: markers need a parent tag"),
    (("sheets", "bid_form", "named_rows", "name_column"), "U",
     r"named_rows\.name_column: must be the name tag column T"),
    (("sheets", "cost_report", "tags", "ref"), "AD", r"tags: key and ref share column AD"),
    (("sheets", "cost_report", "tags", "key"), "D",
     r"tags\.key: D is a visible column; tags are hidden"),
    # Blocks: exactly one owner block per sheet, with a child; ``within`` is
    # the owner's, names the sheet's flat kinds and the owner kind's
    # container; a child's row is a collected kind; the children chain.
    (("sheets", "cost_report", "blocks", "notes"),
     {"marker": {"open": "STEPS", "close": "START"}, "optional": True},
     r"blocks\.notes: a block is an owner \(kind\) or a child \(row\)"),
    (("sheets", "cost_report", "blocks", "activity2"), {"kind": "ACTIVITY"},
     r"blocks: one owner block per sheet \(found activity, activity2\)"),
    (("sheets", "crews", "blocks", "crew"), DELETE, r"crews\.blocks: a blocks sheet needs an owner block"),
    (("sheets", "cost_report", "blocks", "activity", "within"), ["ITEM", "CREW"],
     r"blocks\.activity\.within: CREW is not a row kind of the sheet"),
    (("sheets", "cost_report", "blocks", "steps", "within"), ["ITEM"],
     r"blocks\.steps\.within: only an owner block ends on other rows"),
    (("sheets", "cost_report", "blocks", "activity", "within"), ["GROUP"],
     r"blocks\.activity\.within: must list ITEM, the kind its rows sit under"),
    (("sheets", "cost_report", "blocks", "activity", "within"), DELETE,
     r"blocks\.activity\.within: must list ITEM, the kind its rows sit under"),
    (("sheets", "crews", "blocks", "crew", "children"), [],
     r"blocks\.crew: an owner block needs a child block"),
    (("sheets", "cost_report", "blocks", "steps", "marker"), {"open": "STEPS", "close": "END"},
     r"blocks\.activity: child steps must close with resources's open marker \(START\)"),
    # A growable kind is created from its name; a sheet with resources
    # carries their rate links; a rates sheet is complete; the named rows
    # hold one ESTIMATE row and no other contract kind.
    (("sheets", "cost_report", "fields", "STEP", "name"), DELETE,
     r"fields\.STEP: a growable kind needs its name bound"),
    (("sheets", "cost_report", "fields", "ACTIVITY"), DELETE,
     r"fields\.ACTIVITY: a growable kind needs its name bound"),
    (("sheets", "cost_report", "tags", "ref"), DELETE,
     r"tags: a sheet with resources needs a ref tag \(rate links, contract rule 11\)"),
    (("sheets", "rates", "columns_by_key", "unit"), DELETE,
     r"rates\.columns_by_key: a rates sheet needs id, name, unit and rate"),
    (("sheets", "rates", "sections", "fuel"), "Fuel rates",
     r"rates\.sections: fuel is not a rate kind \(known: labor, equipment, material\)"),
    (("sheets", "rates", "sections"), {}, r"rates\.sections: a rates sheet needs at least one section"),
    (("sheets", "bid_form", "named_rows", "rows", "markup_amount", "kind"), "ESTIMATE",
     r"named_rows: one ESTIMATE row \(markup_percentage and markup_amount\)"),
    (("sheets", "bid_form", "named_rows", "rows", "direct_cost", "kind"), "ITEM",
     r"named_rows\.direct_cost: ITEM is not a named-row kind"),
])
def test_the_loader_refuses_and_names_the_defect(path, value, says):
    with pytest.raises(D.DeclarationError, match=says):
        D.load(_bad(path, value))


def test_a_child_blocks_row_is_a_kind_the_read_model_collects():
    """The reader finds an owner's rows of a child block by the collection
    its row kind names (``contract.COLLECTIONS``), not by the block's name."""
    doc = copy.deepcopy(MINIMAL)
    cr = doc["sheets"]["cost_report"]
    cr["blocks"]["resources"]["row"] = "ELEMENT_QTY"
    del cr["fields"]["RESOURCE"]
    with pytest.raises(D.DeclarationError,
                       match=r"blocks\.resources\.row: ELEMENT_QTY is not a block row kind "
                             r"\(known: STEP, RESOURCE, MEMBER\)"):
        D.load(doc)


def test_a_child_the_owner_row_opens_is_its_first_child():
    """A crew's members block is opened by the CREW row itself; another
    child before it would have nowhere to close."""
    doc = copy.deepcopy(MINIMAL)
    crews = doc["sheets"]["crews"]
    crews["blocks"]["crew"]["children"] = ["notes", "members"]
    crews["blocks"]["notes"] = {"marker": {"open": "NOTES", "close": "CREW"}, "row": "STEP"}
    crews["markers"]["NOTES"] = {}
    with pytest.raises(D.DeclarationError,
                       match=r"blocks\.members: a block the owner row opens must be its first child"):
        D.load(doc)


def test_the_owner_kinds_container_is_required_only_when_the_sheet_lists_it():
    """A sheet without ITEM rows (activities not under items) owes no
    ``within`` -- there is nothing to end an occurrence on."""
    doc = copy.deepcopy(MINIMAL)
    cr = doc["sheets"]["cost_report"]
    cr["rows"] = ["GROUP"]
    cr["blocks"]["activity"]["within"] = ["GROUP"]
    del cr["fields"]["ITEM"]
    cr["formulas"] = {"*": ["AJ"], "ACTIVITY.stepped": ["J"]}
    assert D.load(doc).sheets["cost_report"].blocks["activity"].within == ("GROUP",)


def test_a_growable_kind_cannot_be_a_flat_row():
    doc = copy.deepcopy(MINIMAL)
    cr = doc["sheets"]["cost_report"]
    cr["rows"].append("RESOURCE")
    del cr["blocks"]["resources"]
    cr["blocks"]["activity"]["children"] = ["steps"]
    del doc["prototypes"]["resource"]
    with pytest.raises(D.DeclarationError,
                       match=r"rows: RESOURCE is a growable kind; declare it in a block"):
        D.load(doc)


def test_fixed_blocks_need_no_prototype():
    doc = copy.deepcopy(MINIMAL)
    del doc["prototypes"]["step"]
    doc["sheets"]["cost_report"]["blocks"]["steps"]["fixed"] = True
    assert D.load(doc).growable("cost_report") == ("ACTIVITY", "RESOURCE")


def test_growability_keys_on_the_contract_not_on_recursive():
    """An owner block whose kind the contract lists as growable needs a
    prototype and is growable, whether or not the block is recursive."""
    doc = copy.deepcopy(MINIMAL)
    del doc["sheets"]["cost_report"]["blocks"]["activity"]["recursive"]
    assert D.load(doc).growable("cost_report") == ("ACTIVITY", "STEP", "RESOURCE")
    del doc["prototypes"]["activity"]
    with pytest.raises(D.DeclarationError, match="no prototype for ACTIVITY"):
        D.load(doc)


def test_order_survives_the_stamp():
    """The stamp sorts keys (``stamp.dumps``); the declaration read back from
    a book orders columns by letter and growable kinds by the contract."""
    doc = copy.deepcopy(MINIMAL)
    doc["sheets"]["cost_report"]["columns"]["AA"] = "Note"
    sorted_doc = json.loads(json.dumps(doc, sort_keys=True))
    assert list(sorted_doc["sheets"]["cost_report"]["columns"]) == ["A", "AA", "B", "C", "D", "E"]
    for d in (doc, sorted_doc):
        decl = D.load(d)
        assert decl.visible("cost_report") == ("A", "B", "C", "D", "E", "AA")
        assert decl.growable("cost_report") == ("ACTIVITY", "STEP", "RESOURCE")
        assert decl.growable("crews") == ("MEMBER",)


def test_lift_layout_map_makes_a_flat_declaration():
    lm = {"version": 1,
          "tables": {"index": {"sheet": "Cost Summary", "rows": {"each": "x"},
                               "columns": {"item_no": "A", "descr": "B", "cost": "H", "link": "C"}}},
          "cells": {"direct_total": "Cost Summary!t.d"},
          "tags": {"kind": "Q", "code_chain": "R"},
          "blocks": {"item": "ITEM", "head": "TASK", "body": ["NOTE", "CREW", "LINE"],
                     "end": "END", "sub": "SUBTOTAL", "code_col": "A"},
          "templates": {"rows": {"crew": "CREW", "line": "LINE"}}}
    doc = D.lift_layout_map(lm, pack="fieldbook", version="2")
    decl = D.load(doc)
    assert decl.kind == "recipe" and decl.navigator["tables"]["index"]["sheet"] == "Cost Summary"
    assert decl.sheets == {}                   # fieldbook binds no fields until roadmap 1.11
    assert decl.prototypes == {"task": "est.tpl.task", "crew": "est.tpl.crew",
                               "line": "est.tpl.line"}
