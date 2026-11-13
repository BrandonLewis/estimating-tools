"""Activity and resource descriptions are writable (BidSheet.ai's
``WRITABLE`` for activity.create/update and resource.create/update):
fieldbook binds a task's notes and a line's source and vendor to them.
A copy takes a bound description from its own row, an unbound one from its
source, as before."""
from __future__ import annotations

from estimating_tools.exchange import contract, model
from estimating_tools.exchange.reader import ops
from estimating_tools.heavybook.tests import _readback as H


def test_description_is_writable_for_activities_and_resources():
    assert contract.FIELDS["ACTIVITY"]["description"] == contract.Field("text")
    assert contract.FIELDS["RESOURCE"]["description"] == contract.Field("text")


def test_a_new_activity_sends_its_description_when_the_sheet_binds_it():
    assert "description" in ops._CREATE_FIELDS


def test_a_resource_reads_its_description():
    doc = H.fixture_doc()
    first = doc["resources"][0]
    first["description"] = "QUOTE · Pipe Vendor A"
    parsed = {r.id: r for r in model.parse(doc).resources}
    assert parsed[first["id"]].description == "QUOTE · Pipe Vendor A"


def test_a_copy_takes_a_bound_field_from_its_row_not_its_source():
    raw = {"description": "the source's", "trade": "OPER", "pieces": None}
    assert ops._unpriced(raw, ops.UNPRICED_RESOURCE) == {"description": "the source's",
                                                          "trade": "OPER"}
    assert ops._unpriced(raw, ops.UNPRICED_RESOURCE, bound={"description": "I"}) == {
        "trade": "OPER"}
