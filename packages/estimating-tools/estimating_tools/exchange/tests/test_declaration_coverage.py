"""#439: the loader refuses a declaration that would read a row kind the
baseline holds as deleted -- an owner block without one of its child
blocks, a container sheet without the kinds nested under it."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.tests.test_declaration import MINIMAL


def _doc(change):
    doc = copy.deepcopy(MINIMAL)
    change(doc)
    return doc


def _no_resources(doc):
    cr = doc["sheets"]["cost_report"]
    cr["blocks"]["activity"]["children"] = ["steps"]
    cr["blocks"]["steps"]["marker"] = {"open": "STEPS", "close": "END"}
    del cr["blocks"]["resources"]
    del cr["fields"]["RESOURCE"]
    del doc["prototypes"]["resource"]


def _no_members(doc):
    crews = doc["sheets"]["crews"]
    del crews["blocks"]["members"]
    crews["blocks"]["crew"]["children"] = []
    del crews["fields"]


def _no_quantities(doc):
    doc["sheets"]["cost_report"]["rows"] = ["ITEM", "GROUP"]


@pytest.mark.parametrize("change, says", [
    (_no_resources, "the ACTIVITY block needs a child block for its RESOURCE rows"),
    (_no_quantities, "a sheet with ITEM rows lists ELEMENT_QTY rows too"),
])
def test_a_kind_the_baseline_holds_cannot_be_left_out(change, says):
    with pytest.raises(D.DeclarationError, match=says):
        D.load(_doc(change))


def test_a_crew_block_without_members_is_refused():
    with pytest.raises(D.DeclarationError, match="an owner block needs a child block"):
        D.load(_doc(_no_members))


def test_a_sheet_left_out_altogether_still_loads():
    def change(doc):
        del doc["sheets"]["crews"]
        del doc["sheets"]["bid_form"]
        del doc["prototypes"]["member"]
    decl = D.load(_doc(change))
    assert set(decl.sheets) == {"cost_report", "rates"}
