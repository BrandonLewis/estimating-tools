from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from estimating_tools.heavycivil import columns as C
from estimating_tools.heavycivil import layout as L
from estimating_tools.heavycivil import model
from estimating_tools.heavycivil import style as S


def _plan(doc):
    wb = model.parse(doc)
    return wb, L.plan(wb, S.load_style())


def test_every_item_activity_resource_has_one_row(doc):
    wb, p = _plan(doc)
    assert set(p.item_rows) == {i.id for i in wb.items}
    assert set(p.activity_rows) == {a.id for a in wb.activities}
    assert set(p.resource_rows) == {r.id for r in wb.resources}


def test_rows_are_contiguous_from_first_data_row(doc):
    _, p = _plan(doc)
    numbers = [r.row for r in p.cost_report]
    assert numbers == list(range(L.FIRST_ROW, L.FIRST_ROW + len(numbers)))


def test_resource_span_follows_its_activity(doc):
    """START, resources, then END: the span runs START..END, so a line an
    estimator inserts anywhere inside it (above END included) is summed."""
    wb, p = _plan(doc)
    by_row = {r.row: r for r in p.cost_report}
    for a in wb.activities:
        span = p.resource_span[a.id]
        start, end = p.start_rows[a.id], p.end_rows[a.id]
        assert span == (start.row, end.row)
        for marker, kind in ((start, "START"), (end, "END")):
            assert marker.kind == kind and marker.parent_id == a.id
            assert marker.id is None and marker.v is None
            assert marker.level == p.activity_rows[a.id].level + 1
        rows = [p.resource_rows[r.id].row for r in wb.resources_of(a.id)]
        assert rows == list(range(start.row + 1, end.row))
        assert all(by_row[n].kind == "RESOURCE" for n in range(start.row + 1, end.row))


def test_every_span_has_two_rows_and_starts_after_the_steps(doc):
    """A one-cell span moves (rather than grows) when a row is inserted at
    it, so every span is at least START..END; START sits right after the
    activity's last step (or the activity row)."""
    wb, p = _plan(doc)
    for a in wb.activities:
        first, last = p.resource_span[a.id]
        assert last - first + 1 >= 2
        before = (p.step_rows[a.steps[-1].id].row if a.steps
                  else p.activity_rows[a.id].row)
        assert first == before + 1 == p.start_rows[a.id].row


def test_end_row_comes_before_child_activities(doc):
    wb, p = _plan(doc)
    for a in wb.activities:
        for child in wb.children(a.id):
            assert p.end_rows[a.id].row < p.activity_rows[child.id].row


def test_child_activity_sits_under_its_parent_one_level_deeper(doc):
    wb, p = _plan(doc)
    for a in wb.activities:
        if a.parent_id is not None:
            child, parent = p.activity_rows[a.id], p.activity_rows[a.parent_id]
            assert child.row > parent.row
            assert child.level == parent.level + 1


def test_element_quantity_rows_sit_under_their_paying_item(doc):
    wb, p = _plan(doc)
    for e in wb.elements:
        for q in e.quantities:
            row = p.quantity_rows[(e.id, q.key)]
            if q.pay_item_id is None:
                assert row.row > p.group_row
            else:
                item_row = p.item_rows[q.pay_item_id].row
                assert row.row > item_row


def test_crew_member_span_and_rates_rows(doc):
    wb, p = _plan(doc)
    for c in wb.crews:
        first, last = p.member_span[c.id]
        assert last - first + 1 == len(c.members)
    assert set(p.labor_rate_rows) == {r.id for r in wb.rates_by_kind("labor")}


def test_one_share_row_per_share(doc):
    wb, p = _plan(doc)
    assert len(p.share_rows) == len(wb.shares)


def test_layout_json_documents_row_kinds_not_rows(doc):
    """Read-back keys off the hidden kind/id/v cells; stored row numbers go
    stale the moment an estimator inserts or sorts, so none are stored."""
    wb, p = _plan(doc)
    data = L.layout_json(p, wb, S.load_style())
    assert "rows" not in data
    kinds = {(k["sheet"], k["kind"]): k for k in data["row_kinds"]}
    assert {"ITEM", "ACTIVITY", "RESOURCE", "ELEMENT_QTY", "STEP", "START", "END",
            "GROUP"} <= {
        kind for sheet, kind in kinds if sheet == "cost_report"}
    qty = kinds[("cost_report", "ELEMENT_QTY")]
    assert qty["kind_cell"] == "W"
    assert qty["identified_by"] == {"element_id": "X", "quantity_key": "AD", "v": "Y"}
    for marker in ("START", "END"):
        assert kinds[("cost_report", marker)]["identified_by"] == {"activity_id": "Z"}
        assert kinds[("cost_report", marker)]["editable"] is False
    assert kinds[("crews", "CREW")]["identified_by"] == {"id": "L", "v": "M"}
    assert data["format"] == "heavycivil" and data["layout_version"] == 1
    assert data["first_row"] == L.FIRST_ROW


def test_plan_refuses_an_activity_without_a_row(doc):
    """Belt and braces under model.parse's cycle check: an activity the
    walk never reaches is refused by name, not left row-less."""
    wb = model.parse(doc)
    a = wb.activities[0]
    looped = dataclasses.replace(a, parent_id=a.id)
    wb = dataclasses.replace(wb, activities=(looped,) + wb.activities[1:])
    with pytest.raises(model.PayloadError, match=rf"activity {a.id}: has no Cost Report row"):
        L.plan(wb, S.load_style())


def test_bid_form_groups_items_by_section_then_the_rest(doc):
    wb, p = _plan(doc)
    assert set(p.bid_rows) == {i.id for i in wb.items}
    first, last = p.bid_items_span
    assert first == C.BF.FIRST_ROW
    rows = sorted([r.row for r in p.bid_rows.values()] + [s.row for s in p.bid_sections])
    assert rows == list(range(first, last + 1))
    for sec in (s for s in p.bid_sections if s.kind == "SECTION"):
        members = [i for i in wb.items if i.section_id == sec.id]
        assert all(p.bid_rows[i.id].row > sec.row for i in members)


def test_bid_totals_follow_the_items(doc):
    wb, p = _plan(doc)
    assert [r.obj.name for r in p.bid_total_rows] ==         [t.name for t in sorted(wb.estimate.bid_totals, key=lambda t: t.display_order)]
    assert min(r.row for r in p.bid_total_rows) > p.bid_items_span[1]


def test_primary_total_and_covers(doc):
    wb, _ = _plan(doc)
    base = L.primary_total(wb)
    assert base.name == "Base Bid"
    assert L._covers(base, 1) and not L._covers(base, 2) and L._covers(base, None)
    alt = next(t for t in wb.estimate.bid_totals if not t.is_primary)
    assert L._covers(alt, 2) and not L._covers(alt, None)


def test_schedule_rows_and_calendar(doc):
    wb, p = _plan(doc)
    dated = [a for a in wb.activities if a.start_date and a.finish_date]
    assert set(p.schedule_rows) == {a.id for a in dated}
    assert p.calendar == sorted(p.calendar)
    assert all(d.weekday() < 5 for d in p.calendar)          # fixture: Mon-Fri
    assert date(2026, 11, 26) not in p.calendar               # fixture holiday
    last_finish = max(date.fromisoformat(a.finish_date) for a in dated)
    assert p.calendar[-1] > last_finish
    assert p.weeks[0].weekday() == 0


def test_flat_has_a_line_per_resource_and_crew_charge(doc):
    wb, p = _plan(doc)
    kinds = [r.kind for r in p.flat_rows]
    assert kinds.count("RESOURCE") == len(wb.resources)
    assert kinds.count("CREW_CHARGE") == sum(1 for a in wb.activities if a.crew_id is not None)


def test_layout_json_documents_bid_form_kinds_and_inputs(doc):
    wb, p = _plan(doc)
    data = L.layout_json(p, wb, S.load_style())
    kinds = {(k["sheet"], k["kind"]): k for k in data["row_kinds"]}
    assert kinds[("bid_form", "ITEM_BID")] == {
        "sheet": "bid_form", "kind": "ITEM_BID", "kind_cell": "J",
        "identified_by": {"id": "K", "v": "L"}, "editable": True}
    assert kinds[("bid_form", "ESTIMATE")]["editable"] is True
    assert kinds[("bid_form", "BID_TOTAL")]["editable"] is False
    # Estimate inputs and figures are found by the name marker in T, never
    # by a fixed address: no row number is stored.
    assert data["bid_inputs"] == {
        "name_cell": "T", "value_cell": "C",
        "inputs": ["markup_percentage", "markup_amount"],
        "figures": ["indirect_cost", "direct_cost", "markup_total", "bid_factor",
                    "excluded_cost"]}
    assert "bid_figures" not in data
    assert kinds[("bid_form", "ESTIMATE")]["identified_by"] == {"id": "K", "v": "L",
                                                                "name": "T"}
    assert kinds[("bid_form", "BID_INPUT")] == {
        "sheet": "bid_form", "kind": "BID_INPUT", "kind_cell": "J",
        "identified_by": {"name": "T"}, "editable": True}
    assert kinds[("bid_form", "BID_FIGURE")]["identified_by"] == {"name": "T"}
    assert kinds[("bid_form", "BID_FIGURE")]["editable"] is False


def test_primary_falls_back_to_the_first_definition(doc):
    """``bid_totals.primary_definition``: with none primary, the first in
    display order (then id) stands in."""
    for bt in doc["estimate"]["bid_totals"]:
        bt["is_primary"] = False
    doc["estimate"]["bid_totals"][0]["display_order"] = 5
    wb, _ = _plan(doc)
    assert L.primary_total(wb).name == "Alternate 1"


def test_no_definitions_gives_the_implicit_bid_total(doc):
    """``bid_totals.definitions``: none set is one implicit primary "Bid
    Total" over every schedule and the unscheduled items."""
    doc["estimate"]["bid_totals"] = []
    wb, p = _plan(doc)
    (implicit,) = wb.estimate.bid_totals
    assert (implicit.id, implicit.name, implicit.schedule_ids, implicit.includes_unscheduled,
            implicit.is_primary) == (None, "Bid Total", None, True, True)
    assert L.primary_total(wb) is implicit
    assert [r.obj for r in p.bid_total_rows] == [implicit]


def test_a_section_heads_only_items_on_its_schedule(doc):
    """``bid_totals.section_of``: an item's section counts only when the
    section heads the item's schedule (an unscheduled section, unscheduled
    items)."""
    doc["estimate"]["sections"][0]["schedule_id"] = 2      # items 12/B3 are on schedule 1
    wb, p = _plan(doc)
    assert not [s for s in p.bid_sections if s.kind == "SECTION"]
    doc["estimate"]["sections"][0]["schedule_id"] = None
    for item in doc["items"]:
        if item["item_number"] == "B3":
            item["schedule"] = None
    wb, p = _plan(doc)
    (sec,) = [s for s in p.bid_sections if s.kind == "SECTION"]
    b3 = next(i for i in wb.items if i.item_number == "B3")
    twelve = next(i for i in wb.items if i.item_number == "12")
    assert p.bid_rows[b3.id].row == sec.row + 1
    assert p.bid_rows[twelve.id].row > sec.row + 1          # under "Other items"


def test_working_day_matches_a_compact_iso_holiday():
    conf = {"working_weekdays": None, "holidays": ["20261126"]}
    assert not L._working_day(conf, date(2026, 11, 26))
    assert L._working_day(conf, date(2026, 11, 27))
