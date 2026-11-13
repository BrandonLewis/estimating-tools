"""The read-model collections a display sheet lays out: their orders are
HeavyBook's (the retired code build's layout plan's, on four payloads), their
identities and variants."""
from __future__ import annotations

import pytest

from estimating_tools.exchange import display as D
from estimating_tools.exchange import model
from estimating_tools.heavybook.tests import _readback as H

DOCS = {"golden": H.fixture_doc, "linked": H.linked_doc, "edge": H.edge_doc,
        "implicit": H.implicit_doc}


@pytest.fixture(params=sorted(DOCS))
def wb(request):
    return model.parse(DOCS[request.param]())


#: The orders the retired code build's layout plan gave the four payloads
#: (captured from ``heavybook.layout.plan`` before it retired): the
#: activities in tree order, the scheduled activities, the calendar's first
#: and last working day and its length, the Bid Form's lines, the bid totals
#: and the primary one, the element quantities.
LINES = [("SECTION", 1), ("ITEM_BID", 1), ("ITEM_BID", 2), ("GROUP", None), ("ITEM_BID", 4),
         ("ITEM_BID", 3), ("ITEM_BID", 5)]
CODE_ORDERS = {
    "golden": {"totals": [1, 2], "primary": 1},
    "linked": {"totals": [1, 2], "primary": 1},
    "edge": {"totals": [3], "primary": 3},
    "implicit": {"totals": [None], "primary": None},
}


@pytest.mark.parametrize("label", sorted(DOCS))
def test_the_orders_are_heavybooks(label):
    wb = model.parse(DOCS[label]())
    want = CODE_ORDERS[label]
    assert [a.id for a in D.tree(wb)] == [1, 2, 3, 4, 5, 7, 6, 8]
    assert [a.id for a in D.scheduled(wb)] == [1, 6]
    days = [w.day for w in D.working_days(wb)]
    assert (str(days[0]), str(days[-1]), len(days)) == ("2026-10-26", "2027-11-04", 268)
    assert [(k, getattr(o, "id", None)) for k, o in D.bid_lines(wb)] == LINES
    assert [t.id for t in D.bid_totals(wb)] == want["totals"]
    primary = D.primary_total(wb)
    assert (None if primary is None else primary.id) == want["primary"]
    assert [(q.element_id, q.key) for q in D.quantities(wb)] == [(1, "concrete_cy"),
                                                                  (2, "concrete_cy")]


def test_coverage_lists_each_schedule_a_total_sums():
    cover = [(c.total_key, c.schedule_id, c.primary) for c in D.coverage(model.parse(H.fixture_doc()))]
    assert cover == [("T:1", 1, True), ("T:1", -1, True), ("T:2", 2, False)]
    edge = [(c.total_key, c.schedule_id, c.primary) for c in D.coverage(model.parse(H.edge_doc()))]
    assert edge == [("T:3", 1, True), ("T:3", 2, True)]           # every schedule; first is primary
    implicit = D.coverage(model.parse(H.implicit_doc()))
    assert [(c.total_key, c.schedule_id) for c in implicit] == [("T:", 1), ("T:", 2), ("T:", -1)]


def test_identities_and_variants():
    wb = model.parse(H.edge_doc())
    src = D.SOURCES
    q = D.quantities(wb)[0]
    assert src["ELEMENT_QTY"].ident(q) == f"{q.element_id}:{q.key}"
    assert src["SHARE"].ident(wb.shares[0]) == "1:1:"
    assert src["SHARE"].ident(wb.shares[4]) == "5:1:1"
    assert [m.id for m in src["MISSING_CREW"].rows(wb, None)] == [98, 99]
    assert [a.id for a in src["NO_SHIFTS"].rows(wb, None)] == [7]
    assert [(w.activity.id, w.text) for w in src["WARNING"].rows(wb, None)] == [
        (5, "No production rate")]
    stepped = src["ACTIVITY"].variants["stepped"]
    assert [a.id for a in D.tree(wb) if stepped(wb, a)] == [4]
    assert src["SHARE"].priced and src["COVERAGE"].priced and not src["ITEM"].priced


def test_a_rate_links_as_a_resource_does():
    wb = model.parse(H.fixture_doc())
    assert [r.link for r in wb.rates] == ["labor:1", "material:1"]


def test_two_warnings_on_one_activity_and_rates_of_two_kinds_have_their_own_ids():
    doc = H.linked_doc()
    doc["activities"][0]["warnings"] = ["One", "Two"]
    wb = model.parse(doc)
    warnings = D.SOURCES["WARNING"].rows(wb, None)
    ids = [D.SOURCES["WARNING"].ident(w) for w in warnings]
    assert len(ids) == len(set(ids)) == 2
    labor, material = wb.rates_by_kind("labor")[0], wb.rates_by_kind("material")[0]
    assert labor.id == material.id
    assert (D.child_ident(labor), D.child_ident(material)) == ("labor:1", "material:1")
