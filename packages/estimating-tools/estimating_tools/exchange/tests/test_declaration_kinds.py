"""``kinds:`` (fieldbook spec, "Pack kinds alias contract kinds"): a pack
names its rows as it likes and the declaration says which contract kind
each is. Writability, identity tags, prototypes and what a new row needs
come from the contract kind; bindings belong to the form."""
from __future__ import annotations

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.tests import _forms


def _sheet(doc):
    return D.load(doc).sheets["items"]


def test_forms_are_the_kinds_the_sheet_shows():
    sheet = _sheet(_forms.base())
    assert sheet.kinds() == {"ITEM": "row", "HEAD": "row", "SUBTOTAL": "row",
                             "TASK": "owner", "CREW": "child", "LINE": "child",
                             "END": "marker"}
    assert sheet.forms("RESOURCE") == ("CREW", "LINE")
    assert sheet.forms("ITEM") == ("ITEM",)
    assert (sheet.contract_kind("CREW"), sheet.contract_kind("END")) == ("RESOURCE", "END")


def test_a_form_carries_its_contract_kinds_tags():
    kinds = D.load(_forms.base()).row_kinds()["items"]["kinds"]
    assert kinds["CREW"] == {"id": "W", "v": "X", "parent": "R"}
    assert kinds["TASK"] == {"id": "W", "v": "X", "parent": "R"}
    assert "ACTIVITY" not in kinds and "RESOURCE" not in kinds


def test_an_alias_written_in_a_block_is_resolved():
    doc = _forms.base()
    doc["sheets"]["items"]["blocks"]["task"]["kind"] = "TASK"
    doc["sheets"]["items"]["blocks"]["resources"]["marker"]["open"] = "TASK"
    sheet = _sheet(doc)
    assert sheet.blocks["task"].kind == "ACTIVITY"
    assert sheet.blocks["resources"].open == "ACTIVITY"


@pytest.mark.parametrize("change, says", [
    (lambda d: d["kinds"].update(CREW="CREWE"),
     r"kinds\.CREW: CREWE is not a contract kind"),
    (lambda d: d["kinds"].update(ITEM="ACTIVITY"),
     r"kinds\.ITEM: sheets\.items\.rows lists ITEM -- an aliased kind is shown by its "
     r"contract kind's blocks"),
    (lambda d: d["sheets"]["items"]["fields"].update(RESOURCE={"name": "A"}),
     r"sheets\.items\.fields\.RESOURCE: RESOURCE rows are CREW and LINE on this sheet -- "
     r"bind each of them"),
    (lambda d: d["sheets"]["items"]["fields"]["CREW"].update(markup_percentage="B"),
     r"sheets\.items\.fields\.CREW\.markup_percentage: not writable for RESOURCE"),
    (lambda d: d["prototypes"].pop("line"),
     r"sheets\.items\.blocks\.resources: no prototype for LINE \(prototypes\.line\)"),
    (lambda d: d["sheets"]["items"]["fields"]["CREW"].pop("component_type"),
     r"sheets\.items\.fields\.CREW: a growable kind needs its component_type bound"),
])
def test_the_loader_refuses_and_names_the_defect(change, says):
    doc = _forms.base()
    change(doc)
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)


def test_a_declaration_without_kinds_is_unchanged():
    from estimating_tools.heavybook.pack import pack

    decl = pack().declaration()
    assert decl.aliases == {}
    for sheet in decl.sheets.values():
        for b in sheet.blocks.values():
            for kind in (b.kind, b.row):
                if kind:
                    assert sheet.forms(kind) == (kind,)


def _flat_bid(d):
    d["kinds"]["BID"] = "ITEM"


def _marker_alias(d):
    d["sheets"]["items"]["markers"]["LINE"] = {}


def _banner_alias(d):
    d["sheets"]["items"]["blocks"]["task"]["banner"] = "CREW"


def _named_alias(d):
    d["sheets"]["items"]["tags"]["name"] = "V"
    d["sheets"]["items"]["named_rows"] = {"name_column": "V", "value_column": "B",
                                          "rows": {"bid": {"kind": "TASK"}}}


@pytest.mark.parametrize("change, says", [
    (_flat_bid, r"kinds\.BID: sheets\.items\.rows lists ITEM -- a kind with forms is shown by "
                r"its forms"),
    (_marker_alias, r"kinds\.LINE: sheets\.items\.markers names LINE -- an aliased kind is "
                    r"shown by its contract kind's blocks"),
    (_banner_alias, r"kinds\.CREW: sheets\.items\.blocks\.task\.banner names CREW -- an aliased "
                    r"kind is shown by its contract kind's blocks"),
    (_named_alias, r"kinds\.TASK: sheets\.items\.named_rows\.rows\.bid names TASK -- an aliased "
                   r"kind is shown by its contract kind's blocks"),
])
def test_an_aliased_name_is_used_where_the_loader_cannot_resolve_it(change, says):
    doc = _forms.base()
    change(doc)
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)
