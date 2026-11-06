from __future__ import annotations

import copy

import pytest

from estimating_tools.exchange import model


def _pages(doc):
    """Split the fixture into two pages the way BidSheet.ai pages by item_ids."""
    items = [i["id"] for i in doc["items"]]
    first, second = set(items[:2]), set(items[2:])
    pages = []
    for ids in (first, second):
        page = copy.deepcopy(doc)
        page["items"] = [i for i in doc["items"] if i["id"] in ids]
        page["activities"] = [a for a in doc["activities"] if a["estimate_item_id"] in ids]
        acts = {a["id"] for a in page["activities"]}
        page["resources"] = [r for r in doc["resources"] if r["activity_id"] in acts]
        page["shares"] = [s for s in doc["shares"] if s["item_id"] in ids or s["activity_id"] in acts]
        pages.append(page)
    return pages


def test_merged_pages_equal_the_whole(doc):
    merged = model.merge_pages(_pages(doc))
    whole = model.parse(doc)
    got = model.parse(merged)
    assert {i.id for i in got.items} == {i.id for i in whole.items}
    assert {a.id for a in got.activities} == {a.id for a in whole.activities}
    assert {r.id for r in got.resources} == {r.id for r in whole.resources}
    assert sorted((s.activity_id, s.item_id) for s in got.shares) == \
        sorted((s.activity_id, s.item_id) for s in whole.shares)


def test_pages_of_different_estimates_are_refused(doc):
    a, b = _pages(doc)
    b["estimate"]["id"] = a["estimate"]["id"] + 1
    with pytest.raises(model.PayloadError, match="estimate"):
        model.merge_pages([a, b])


def test_a_row_that_changed_between_pages_is_refused(doc):
    a, b = _pages(doc)
    shared = copy.deepcopy(a["items"][0])
    shared["v"] = "0" * 16
    b["items"].append(shared)
    with pytest.raises(model.PayloadError, match="re-fetch"):
        model.merge_pages([a, b])


def test_one_page_is_returned_as_is(doc):
    assert model.merge_pages([doc]) == doc


def test_merge_is_independent_of_page_order(doc):
    pages = _pages(doc)
    forward = model.merge_pages(pages)
    assert model.merge_pages(list(reversed(copy.deepcopy(pages)))) == forward
    # ... and in the order BidSheet.ai gives one whole payload.
    for key in ("items", "activities", "resources", "elements"):
        assert [r["id"] for r in forward[key]] == [r["id"] for r in doc[key]], key


def test_items_sort_like_order_by_item_number_numeric():
    """Leading digits numerically (padded to 6), no digits last, then the
    item number, then the item code."""
    rows = [{"id": n, "item_number": num, "item_code": code} for n, (num, code) in enumerate(
        [("B3", ""), ("10", ""), ("2A", ""), ("2", ""), ("A1", "z"), ("A1", "a")])]
    ordered = sorted(rows, key=model._item_order_key)
    assert [(r["item_number"], r["item_code"]) for r in ordered] == [
        ("2", ""), ("2A", ""), ("10", ""), ("A1", "a"), ("A1", "z"), ("B3", "")]


def test_an_estimate_that_changed_between_pages_is_refused(doc):
    a, b = _pages(doc)
    b["estimate"]["markup_percentage"] = "12.00"
    with pytest.raises(model.PayloadError, match="estimate changed between fetches; re-fetch"):
        model.merge_pages([a, b])


def test_conflicting_shares_are_refused(doc):
    a, b = _pages(doc)
    shared = copy.deepcopy(a["shares"][0])
    shared["fraction"] = "0.5"
    b["shares"].append(shared)
    with pytest.raises(model.PayloadError, match="share"):
        model.merge_pages([a, b])


def test_conflicting_rates_are_refused(doc):
    a, b = _pages(doc)
    b["rates"]["labor"][0]["rate"] = "99.00"
    with pytest.raises(model.PayloadError, match="rates.labor"):
        model.merge_pages([a, b])


@pytest.mark.parametrize("rates", [[], {"labor": {}}, {"labor": ["x"]}])
def test_malformed_rates_are_refused(doc, rates):
    a, b = _pages(doc)
    b["rates"] = rates
    with pytest.raises(model.PayloadError, match="rates"):
        model.merge_pages([a, b])


@pytest.mark.parametrize("section", ["shares", "items"])
def test_non_object_rows_are_refused(doc, section):
    a, b = _pages(doc)
    b[section] = ["x"]
    with pytest.raises(model.PayloadError, match=section):
        model.merge_pages([a, b])


def test_merge_pages_unions_the_fetch_record(doc):
    a, b = copy.deepcopy(doc), copy.deepcopy(doc)
    a["items"], b["items"] = doc["items"][:2], doc["items"][2:]
    a["_fetch"] = {"item_ids": [1, 4]}
    b["_fetch"] = {"item_ids": [2, 3, 5]}
    assert model.merge_pages([a, b])["_fetch"] == {"item_ids": [1, 2, 3, 4, 5]}
    del b["_fetch"]
    assert "_fetch" not in model.merge_pages([a, b])     # one whole page: the whole estimate


def test_a_malformed_fetch_record_on_any_page_refuses_the_merge(doc):
    """Every page's record is validated (``fetch_record``): a wrong one is a
    payload refusal, never a ``TypeError`` or a quietly dropped record."""
    a, b = copy.deepcopy(doc), copy.deepcopy(doc)
    a["items"], b["items"] = doc["items"][:2], doc["items"][2:]
    a["_fetch"] = {"item_ids": [1, 4]}
    b["_fetch"] = {"item_ids": ["x"]}
    with pytest.raises(model.PayloadError, match="_fetch.item_ids"):
        model.merge_pages([a, b])


def test_a_single_page_with_a_malformed_fetch_record_is_refused(doc):
    page = copy.deepcopy(doc)
    page["_fetch"] = {"item_ids": [True]}
    with pytest.raises(model.PayloadError, match="_fetch.item_ids"):
        model.merge_pages([page])


@pytest.mark.parametrize("rec, want", [
    (None, None), ({"item_ids": [3, 1]}, [3, 1]),
])
def test_fetch_record_reads_the_ids(doc, rec, want):
    page = copy.deepcopy(doc)
    page["_fetch"] = rec
    assert model.fetch_record(page) == want
    assert model.fetch_record({"items": []}) is None


@pytest.mark.parametrize("rec", [
    {"item_ids": [1.5]}, {"item_ids": [None]}, {"item_ids": []}, {"item_ids": "3"},
    {}, "3", [3],
])
def test_fetch_record_refuses_a_wrong_record(rec):
    with pytest.raises(model.PayloadError, match="_fetch.item_ids"):
        model.fetch_record({"_fetch": rec})
