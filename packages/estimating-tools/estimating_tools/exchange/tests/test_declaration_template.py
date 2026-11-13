"""What a template pack's declaration adds (engine step 4): ``display``
sheets of read-model rows, ``labels`` (read-model values a fill writes and
nothing reads back), ``header`` cells -- and the loader's refusals."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange import labels
from estimating_tools.exchange.tests import _template as T


def _doc(change=None):
    doc = copy.deepcopy(T.DECLARATION)
    if change is not None:
        change(doc)
    return doc


def test_the_test_packs_declaration_loads():
    decl = D.load(_doc())
    est, shares = decl.sheets["estimate"], decl.sheets["shares"]
    assert shares.role == "display" and shares.regions == (D.Region(2, ("SHARE",)),)
    assert est.labels["ELEMENT_QTY"]["B"] == labels.Label("element.name")
    assert est.labels["ITEM"]["A"].path == "item_number"
    assert set(est.header) == {"A1", "A2"}


def _set(path, value):
    def change(doc):
        node = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return change


@pytest.mark.parametrize("path, value, says", [
    (("sheets", "shares", "blocks"), {"x": {"row": "STEP"}}, "a display sheet lays out"),
    (("sheets", "shares", "rows"), ["ITEM"], "a display sheet lists its kinds in regions"),
    (("sheets", "shares", "tags"), {}, "a display sheet needs a kind tag"),
    (("sheets", "estimate", "labels", "ITEM", "C"), "colour", "Item has no colour"),
    (("sheets", "estimate", "labels", "ITEM", "E"), "description", "E holds a ITEM tag, field or export value"),
    (("sheets", "estimate", "labels", "ITEM", "H"), "description", "H holds a ITEM tag"),
    # Every tag column, whatever kind the tag is for: a label would
    # overwrite the rate link (L, ``ref``, on a resource) or the parent chain (J).
    (("sheets", "estimate", "labels", "RESOURCE"), {"L": "name"}, "L holds a RESOURCE tag"),
    (("sheets", "estimate", "labels", "ITEM", "J"), "description", "J holds a ITEM tag"),
    # A label ends on a value: a scalar field or a key of a table.
    (("sheets", "estimate", "labels", "RESOURCE"), {"R": "activity"}, "activity is a relation"),
    (("sheets", "estimate", "labels", "ACTIVITY", "R"), "cost_split", "cost_split is a table"),
    (("sheets", "estimate", "labels", "ACTIVITY", "R"), "item", "item is a relation"),
    (("sheets", "estimate", "labels", "ACTIVITY", "R"), "steps", "steps is a list"),
    (("sheets", "estimate", "labels", "ACTIVITY", "R"), "steps.name", "steps is a list"),
    (("sheets", "estimate", "header", "A2"), "estimate.schedule", "schedule is a table"),
    (("sheets", "estimate", "header", "A2"), "estimate.sections", "sections is a list"),
    (("sheets", "estimate", "labels", "ACTIVITY", "R"), "cost_split.labor.x", "a key of a table ends the path"),
    (("sheets", "estimate", "labels", "ACTIVITY", "R"), "Total", "is not a path"),
    (("sheets", "estimate", "labels", "ACTIVITY", "R"), "name.first", "name is not a table or a relation"),
    (("sheets", "estimate", "labels", "ELEMENT_QTY", "R"), "element.colour", "Element has no colour"),
    (("sheets", "estimate", "labels", "ITEM", "R"), "{description}", "compose text with a template formula"),
    (("sheets", "estimate", "labels", "SHARE"), {"R": "fraction"}, "SHARE is not a row kind"),
    (("sheets", "estimate", "header", "A9"), "host", "sits above first_row"),
    (("sheets", "estimate", "header", "A2"), "estimate.colour", "the estimate has no colour"),
    (("sheets", "estimate", "header", "A2"), "exported_at.day", "has no fields"),
])
def test_the_loader_refuses_and_names_the_defect(path, value, says):
    with pytest.raises(D.DeclarationError, match=says):
        D.load(_doc(_set(path, value)))


def test_a_label_may_sit_on_the_ref_column_of_a_kind_that_carries_no_ref():
    # Only a resource (and a crew member) stores a ``ref``; on an item's row
    # the column is free -- HeavyBook keeps an item's scope and an element
    # quantity's element there (``AE``), where its formulas read them.
    decl = D.load(_doc(_set(("sheets", "estimate", "labels", "ITEM", "L"), "scope")))
    assert decl.sheets["estimate"].labels["ITEM"]["L"].path == "scope"
    with pytest.raises(D.DeclarationError, match="L holds a RESOURCE tag"):
        D.load(_doc(_set(("sheets", "estimate", "labels", "RESOURCE"), {"L": "name"})))


def test_a_flat_sheets_header_cell_may_sit_among_its_named_rows():
    # A flat sheet reads from row 1 (its named rows) but the fill places
    # rows only at its regions: a header cell above the first region is
    # never moved (HeavyBook's Bid Form keeps the estimate's name in U2).
    decl = D.load(_doc(_set(("sheets", "bid", "header"), {"U2": "estimate.name"})))
    assert decl.sheets["bid"].header["U2"].path == "estimate.name"
    with pytest.raises(D.DeclarationError, match=r"bid.header.U7: a header cell sits above "
                                                 r"the first region \(7\)"):
        D.load(_doc(_set(("sheets", "bid", "header"), {"U7": "estimate.name"})))


def test_a_table_key_and_a_relation_are_paths():
    decl = D.load(_doc(_set(("sheets", "estimate", "labels", "RESOURCE"),
                            {"R": "activity.item.item_number"})))
    assert decl.sheets["estimate"].labels["RESOURCE"]["R"].path == "activity.item.item_number"
    D.load(_doc(_set(("sheets", "estimate", "labels", "ACTIVITY", "R"), "cost_split.labor")))


def test_a_label_resolves_through_the_read_model():
    from estimating_tools.exchange import model
    from estimating_tools.heavybook.tests import _readback as H

    wb = model.parse(H.fixture_doc())
    res, act = wb.resources[0], wb.activity(1)
    assert labels.resolve(labels.parse("activity.item.item_number"), res, wb) == \
        wb.item(wb.activity(res.activity_id).item_id).item_number
    assert labels.resolve(labels.parse("cost_split.labor"), act, wb) == act.cost_split["labor"]
    assert labels.resolve(labels.parse("crew.name"), wb.activity(2), wb) is None   # no crew
    assert labels.resolve(labels.parse("start_date"), act, wb) == labels.serial(act.start_date)
