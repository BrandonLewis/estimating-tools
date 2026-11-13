"""The binding forms (fieldbook spec, "What the engine needs from this
spec"; engine spec, ``by_name``): pure data, each with the rules that keep
it readable."""
from __future__ import annotations

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.tests import _forms


def _items(doc=None):
    return D.load(doc or _forms.with_bindings()).sheets["items"]


def test_each_form_parses():
    sheet = _items()
    assert sheet.binding("TASK", "name") == D.Binding(column="B")
    assert sheet.binding("TASK", "description") == D.Binding(column="A", rows="NOTE", sep="\n")
    assert sheet.binding("LINE", "description") == D.Binding(cells=("I", "J"), sep=" · ")
    assert sheet.binding("CREW", "unit_cost") == D.Binding(from_rate="rate")
    assert sheet.binding("TASK", "hours_per_shift") == D.Binding(by_name="est.shift_hours")
    assert sheet.binding("TASK", "count") is None
    assert sheet.spellings == {"component_type": {"Subcontract": "subcontractor"}}


def test_a_joined_row_kind_is_a_kind_of_the_sheet():
    sheet = _items()
    assert sheet.kinds()["NOTE"] == "joined"
    assert sheet.joined() == ("NOTE",)


def test_a_rows_join_owns_no_column_of_its_owners_row():
    """The NOTE rows' A is not the TASK row's: TASK may still bind A."""
    doc = _forms.with_bindings()
    doc["sheets"]["items"]["fields"]["TASK"]["name"] = "A"
    assert _items(doc).binding("TASK", "name") == D.Binding(column="A")


def _untag_rates(d):
    rates = d["sheets"]["rates"]
    rates["tags"].pop("ref")
    rates.pop("local_suffix")
    rates["columns_by_key"].update(id="A", unit="B")


@pytest.mark.parametrize("change, says", [
    (lambda s, d: s["fields"]["CREW"].update(
        description={"rows": "NOTE", "column": "A", "join": "\n"}),
     r"sheets\.items\.fields\.CREW\.description: a rows join binds an owner's field"),
    (lambda s, d: s["fields"]["TASK"].update(
        description={"rows": "STEP", "column": "A", "join": "\n"}),
     r"sheets\.items\.fields\.TASK\.description: STEP is a contract kind"),
    (lambda s, d: s["fields"]["TASK"].update(
        description={"rows": "HEAD", "column": "A", "join": "\n"}),
     r"sheets\.items\.fields\.TASK\.description: HEAD is already a row kind of this sheet"),
    (lambda s, d: s["fields"]["LINE"].update(description={"cells": ["I", "K"], "join": "-"}),
     r"sheets\.items\.fields\.LINE\.description: K is not a visible column"),
    (lambda s, d: s["fields"]["LINE"].update(quantity={"cells": ["B", "C"], "join": "-"}),
     r"sheets\.items\.fields\.LINE\.quantity: a join binds a text field"),
    (lambda s, d: s["fields"]["CREW"].update(component_type={"from_rate": "rate"}),
     r"sheets\.items\.fields\.CREW\.component_type: from_rate: rate binds unit_cost"),
    (lambda s, d: _untag_rates(d), r"from_rate needs a tagged rates sheet"),
    (lambda s, d: s["fields"]["LINE"].update(unit={"by_name": "est.unit"}),
     r"sheets\.items\.fields\.LINE\.unit: by_name binds a number"),
    (lambda s, d: s["spellings"].update(component_type={"Subcontract": "sub"}),
     r"sheets\.items\.spellings\.component_type\.Subcontract: 'sub' is not one of labor"),
    (lambda s, d: s["spellings"].update(name={"X": "y"}),
     r"sheets\.items\.spellings\.name: name is not a coded field"),
    (lambda s, d: s["fields"]["TASK"].update(
        description={"rows": "TASK", "column": "A", "join": "\n"}),
     r"sheets\.items\.fields\.TASK\.description: TASK is already an owner kind of this sheet"),
    (lambda s, d: s["markers"].update(NOTE={}),
     r"sheets\.items\.markers\.NOTE: NOTE is a joined row kind \(fields\.TASK\.description\), "
     r"not a marker"),
])
def test_the_loader_refuses_and_names_the_defect(change, says):
    doc = _forms.with_bindings()
    change(doc["sheets"]["items"], doc)
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)
