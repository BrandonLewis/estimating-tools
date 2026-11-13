"""``each:`` (one sheet per container row) and a derived parent on an
owner whose block does not recurse."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.tests import _forms
from estimating_tools.exchange.tests.test_declaration import MINIMAL


def test_an_each_sheet_expands_into_one_sheet_per_tab():
    decl = D.load(_forms.full())
    sheet = decl.sheets["items"]
    assert (sheet.each, sheet.tab) == ("ITEM", "")
    out = decl.expand(lambda s: ["1 - MOBILIZATION", "2 - 8IN MAIN"])
    assert [(k, s.tab) for k, s in out.sheets.items()] == [
        ("items.1", "1 - MOBILIZATION"), ("items.2", "2 - 8IN MAIN"), ("rates", "Rates")]
    assert out.sheets["items.2"].fields == sheet.fields
    assert out.row_kinds()["items.1"] == out.row_kinds()["items.2"]


def test_a_declaration_without_each_expands_to_itself():
    decl = D.load(copy.deepcopy(MINIMAL))
    assert decl.expand(lambda s: ["never asked"]) is decl


def test_a_non_recursive_owners_parent_may_be_derived():
    sheet = D.load(_forms.full()).sheets["items"]
    assert "ACTIVITY" in sheet.tags["parent"].derived


@pytest.mark.parametrize("change, says", [
    (lambda d: d["sheets"]["items"].update(each="HEAD"),
     r"sheets\.items\.each: a sheet repeats per row of its owner's container \(ITEM\), "
     r"listed in rows"),
    (lambda d: d["sheets"]["items"]["blocks"]["task"].update(recursive=True),
     r"sheets\.items\.tags\.parent\.derived: ACTIVITY opens a recursive block; its parent is "
     r"stored, not derived"),
])
def test_the_loader_refuses_and_names_the_defect(change, says):
    doc = _forms.full()
    change(doc)
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)


def test_a_recursive_owners_parent_stays_stored():
    doc = copy.deepcopy(MINIMAL)
    doc["sheets"]["cost_report"]["tags"]["parent"] = {"column": "Z", "derived": ["ACTIVITY"]}
    with pytest.raises(D.DeclarationError, match="ACTIVITY opens a recursive block"):
        D.load(doc)


def test_two_sheets_repeating_per_one_container_are_refused():
    doc = _forms.full()
    doc["sheets"]["items2"] = copy.deepcopy(doc["sheets"]["items"])
    with pytest.raises(D.DeclarationError,
                       match=r"sheets\.items2\.each: sheets\.items already repeats per ITEM"):
        D.load(doc)


def test_a_non_recursive_owners_id_stays_stored():
    """Only the parent may be derived on a non-recursive owner, and the
    message for any other tag does not call the block recursive."""
    doc = _forms.full()
    doc["sheets"]["items"]["tags"]["id"] = {"column": "W", "derived": ["ACTIVITY"]}
    with pytest.raises(D.DeclarationError,
                       match=r"sheets\.items\.tags\.id\.derived: ACTIVITY opens a block; its id "
                             r"is stored, not derived"):
        D.load(doc)


@pytest.mark.parametrize("change, says", [
    (lambda s: s.update(tab="Items"), r"^sheets\.items: name a tab or each, not both$"),
    (lambda s: s.pop("each"), r"^sheets\.items: name a tab or each$"),
])
def test_a_sheet_names_a_tab_or_each(change, says):
    doc = _forms.full()
    change(doc["sheets"]["items"])
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)
