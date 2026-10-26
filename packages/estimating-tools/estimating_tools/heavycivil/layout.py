"""The row plan: every HeavyCivil row, decided before anything is written.

Formulas reference rows that come later (an activity sums the resources
under it; an item sums its shares, which live on another sheet), so the
whole book is planned first. Sub-project 3's read-back imports this module
and ``columns.py`` -- the writer and the reader share one plan, so they can
never disagree about where an id, a ``v`` or an input cell sits.

Cost Report order, per item (payload order): the ITEM row; the ELEMENT_QTY
rows of quantities paying it (element display order, then key); then its
root activities (sort_order, id), each as ACTIVITY, a STEPS marker row and
its STEPs (a stepped activity only), a START marker row, its RESOURCEs, an
END marker row, then its child activities, depth-first.
Quantities paying no item close the sheet under a GROUP row.

**Read-back contract.** Read-back identifies rows by the hidden W/X/Y/AD
cells (kind, id, ``v``, quantity key; Z is the parent id) -- never by row
number. Row numbers go stale the moment an estimator inserts, deletes or
sorts, so ``_wb`` stores none: it stores the column letters and, per row
kind, which hidden cells identify a row (``row_kinds``). The plan's row
numbers are the writer's, used to lay formulas out at build time.

START and END rows bracket each activity's resource range:
``resource_span`` is always (START row, END row), at least two rows. Excel
grows a range when a row is inserted strictly inside it but *moves* a
one-row range inserted at, so the bracket guarantees a line inserted above
END (or anywhere between the markers) is inside every ``SUM``/``SUMIF``
over the span -- even for an activity with no resources. Markers carry the
kind (W) and the activity id (Z) only: no id, no ``v``, nothing in the cost
columns, so they add nothing to a sum. They are not editable.

A stepped activity's STEPS and START rows bracket its steps the same way:
``step_span`` is (STEPS row, START row), and its Shifts formula sums that
range, so a step inserted anywhere between them counts. An unstepped
activity has no STEPS row (its Shifts is a typed input).

Every Cost Report data row carries AJ, the row of the nearest ACTIVITY at
or above (``formulas.activity_row``); resource formulas read their
activity's cells through it, so a copied resource row prices against the
activity it lands in.

Crews: each crew block is its CREW row, a NOTE row (a library crew's
banner: kind in K, crew id in N), its MEMBERs, then a CREW_END marker
(kind, crew id, a cue). ``crew_span`` is (CREW row, CREW_END row): the
headcount and crew rate sum it, so a member inserted anywhere in the block
counts.

Hidden helper cells by kind (Cost Report): ITEM -- AE scope, AF schedule
qty, AG effective qty, AH breakdown total, AI calculated unit price (as of
export for an item excluded at export), AB
total at export. ELEMENT_QTY -- Z paying item, AD key, AE element id, AG
effective qty, AH override at export. ACTIVITY -- AA multiplier, AB/AC
cost/MH at export, AE crew id, AF in-bid fraction, AH/AI a missing crew's
per-shift labour/MH at export. RESOURCE -- AB cost at export, AE rate link
(``labor:<id>``, ``equipment:<id>`` or ``material:<id>``; empty when
unlinked), AF units, AG per-unit cost. Every row -- AJ activity row.

Bid Form estimate rows (``BF.ROWS``): each carries its name (a
``BF.ROWS`` key) in the hidden T and a kind in J -- ESTIMATE on the first
row (markup %, which also carries the estimate id/``v`` in K/L), BID_INPUT
on the other editable inputs (``BF.INPUTS``), BID_FIGURE on the derived or
as-of-export figures. The value is in C. Read-back finds an input by its
name in T, never by its row.

Schedule hidden cells (one ACTIVITY row per dated activity): G kind, H id,
I export finish, J per-pass ``duration_days`` at export, K the count
multiplier at export (own count x every ancestor's). The export dates span
J x K working days; the live finish moves by CEILING(E) - CEILING(J x K).
Week columns start at L.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from estimating_tools.heavycivil import FORMAT_NAME
from estimating_tools.heavycivil import columns as C
from estimating_tools.heavycivil.model import PayloadError, parse_iso_date

LAYOUT_VERSION = 2
HEADER_ROW = 4
FIRST_ROW = 5
SHARES_FIRST_ROW = 2
CALENDAR_TAIL_DAYS = 260   # working days kept past the last finish, for bars to grow into
#: Calendar days the working-day calendar starts before the earliest start,
#: so a start on a non-working day still MATCHes the working day before it.
CALENDAR_LEAD_DAYS = 7
MAX_WEEKS = 260


@dataclass
class Row:
    row: int
    kind: str
    id: object = None
    v: str | None = None
    parent_id: object = None
    level: int = 0
    obj: object = None


@dataclass
class Plan:
    tabs: dict
    cost_report: list = field(default_factory=list)
    item_rows: dict = field(default_factory=dict)
    activity_rows: dict = field(default_factory=dict)
    resource_rows: dict = field(default_factory=dict)
    step_rows: dict = field(default_factory=dict)
    #: stepped activity id -> its STEPS marker Row.
    steps_rows: dict = field(default_factory=dict)
    #: stepped activity id -> (STEPS row, START row): the rows Shifts sums.
    step_span: dict = field(default_factory=dict)
    quantity_rows: dict = field(default_factory=dict)
    #: activity id -> (START row, END row): the rows its formulas sum.
    resource_span: dict = field(default_factory=dict)
    start_rows: dict = field(default_factory=dict)
    end_rows: dict = field(default_factory=dict)
    group_row: int | None = None
    crews: list = field(default_factory=list)
    crew_rows: dict = field(default_factory=dict)
    member_rows: dict = field(default_factory=dict)
    member_span: dict = field(default_factory=dict)
    #: crew id -> its CREW_END marker Row.
    crew_end_rows: dict = field(default_factory=dict)
    #: crew id -> (CREW row, CREW_END row): the rows headcount and rate sum.
    crew_span: dict = field(default_factory=dict)
    rates: list = field(default_factory=list)
    labor_rate_rows: dict = field(default_factory=dict)
    labor_span: tuple | None = None
    share_rows: list = field(default_factory=list)
    shares_last_row: int = SHARES_FIRST_ROW - 1
    cost_report_last_row: int = FIRST_ROW - 1
    #: name -> row for every estimate cell (BF.ROWS: the editable BF.INPUTS
    #: and the derived figures).
    bid_inputs: dict = field(default_factory=dict)
    bid_rows: dict = field(default_factory=dict)       # item id -> Row (ITEM_BID)
    bid_sections: list = field(default_factory=list)   # Row(kind SECTION or GROUP)
    bid_items_span: tuple | None = None                # (first, last) row of the item block
    bid_total_rows: list = field(default_factory=list)  # Row(kind BID_TOTAL, obj=BidTotal)
    recap_rows: dict = field(default_factory=dict)     # item id -> row
    recap_total_row: int | None = None
    schedule_rows: dict = field(default_factory=dict)  # activity id -> row
    calendar: list = field(default_factory=list)       # working days (date), ascending
    weeks: list = field(default_factory=list)          # Monday of each week column
    flat_rows: list = field(default_factory=list)      # Row(kind CREW_CHARGE|RESOURCE)


def _cost_report(p, wb):
    rows = p.cost_report
    nxt = [FIRST_ROW]

    def add(kind, **kw):
        r = Row(row=nxt[0], kind=kind, **kw)
        rows.append(r)
        nxt[0] += 1
        return r

    def activity(a, depth):
        r = add("ACTIVITY", id=a.id, v=a.v, parent_id=a.parent_id, level=1 + depth, obj=a)
        p.activity_rows[a.id] = r
        if a.steps:
            p.steps_rows[a.id] = add("STEPS", parent_id=a.id, level=depth + 2)
        for s in a.steps:
            p.step_rows[s.id] = add("STEP", id=s.id, v=s.v, parent_id=a.id, level=depth + 2, obj=s)
        start = p.start_rows[a.id] = add("START", parent_id=a.id, level=depth + 2)
        if a.steps:
            p.step_span[a.id] = (p.steps_rows[a.id].row, start.row)
        for res in wb.resources_of(a.id):
            p.resource_rows[res.id] = add("RESOURCE", id=res.id, v=res.v, parent_id=a.id,
                                          level=depth + 2, obj=res)
        end = p.end_rows[a.id] = add("END", parent_id=a.id, level=depth + 2)
        p.resource_span[a.id] = (start.row, end.row)
        for child in wb.children(a.id):
            activity(child, depth + 1)

    quantities = [(e, q) for e in sorted(wb.elements, key=lambda e: (e.display_order, e.id))
                  for q in sorted(e.quantities, key=lambda q: q.key)]
    for item in wb.items:
        p.item_rows[item.id] = add("ITEM", id=item.id, v=item.v, level=0, obj=item)
        for e, q in quantities:
            if q.pay_item_id == item.id:
                p.quantity_rows[(e.id, q.key)] = add("ELEMENT_QTY", id=e.id, v=q.v,
                                                     parent_id=item.id, level=1, obj=(e, q))
        for root in wb.roots(item.id):
            activity(root, 0)
    unassigned = [(e, q) for e, q in quantities if q.pay_item_id is None]
    if unassigned:
        p.group_row = add("GROUP", level=0).row
        for e, q in unassigned:
            p.quantity_rows[(e.id, q.key)] = add("ELEMENT_QTY", id=e.id, v=q.v, level=1, obj=(e, q))
    p.cost_report_last_row = nxt[0] - 1


def _crews(p, wb):
    r = FIRST_ROW
    for crew in wb.crews:
        p.crew_rows[crew.id] = Row(row=r, kind="CREW", id=crew.id, v=crew.v, obj=crew)
        p.crews.append(p.crew_rows[crew.id])
        head = r
        r += 1
        if crew.scope == "library":
            p.crews.append(Row(row=r, kind="NOTE", parent_id=crew.id))
            r += 1
        first = r
        for m in sorted(crew.members, key=lambda m: (m.sort_order, m.classification, m.id)):
            p.member_rows[m.id] = Row(row=r, kind="MEMBER", id=m.id, parent_id=crew.id, obj=m)
            p.crews.append(p.member_rows[m.id])
            r += 1
        p.member_span[crew.id] = (first, r - 1)
        # The marker takes the place of the old blank row between crews.
        p.crew_end_rows[crew.id] = Row(row=r, kind="CREW_END", parent_id=crew.id)
        p.crews.append(p.crew_end_rows[crew.id])
        p.crew_span[crew.id] = (head, r)
        r += 1


def _rates(p, wb):
    r = 1
    for kind in ("labor", "equipment", "material"):
        p.rates.append(Row(row=r, kind="RATE_TITLE", id=kind))
        p.rates.append(Row(row=r + 1, kind="RATE_HEAD", id=kind))
        r += 2
        first = r
        for rate in wb.rates_by_kind(kind):
            row = Row(row=r, kind="RATE", id=rate.id, parent_id=kind, obj=rate)
            p.rates.append(row)
            if kind == "labor":
                p.labor_rate_rows[rate.id] = row
            r += 1
        if kind == "labor" and r > first:
            p.labor_span = (first, r - 1)
        r += 1


def _shares(p, wb):
    r = SHARES_FIRST_ROW
    for share in wb.shares:
        p.share_rows.append(Row(row=r, kind="SHARE", id=share.activity_id,
                                parent_id=share.item_id, obj=share))
        r += 1
    p.shares_last_row = r - 1


def _covers(total, schedule_id):
    """``EstimateBidTotal.covers``."""
    if schedule_id is None:
        return total.includes_unscheduled
    return total.schedule_ids is None or schedule_id in total.schedule_ids


def _definitions(wb):
    """``bid_totals.definitions``' order: display order, then id."""
    return sorted(wb.estimate.bid_totals,
                  key=lambda t: (t.display_order, -1 if t.id is None else t.id))


def primary_total(wb):
    """``bid_totals.primary_definition``: the primary total, else the first
    definition (``model.parse`` supplies the implicit one when none is set)."""
    defs = _definitions(wb)
    return next((t for t in defs if t.is_primary), defs[0] if defs else None)


def section_of(wb, item):
    """``bid_totals.section_of``: the item's section, or None when it has
    none or the section heads another schedule than the item's."""
    sec = next((s for s in wb.estimate.sections if s.id == item.section_id), None)
    if sec is None or sec.schedule_id != item.schedule_id:
        return None
    return sec


def _bid_form(p, wb):
    p.bid_inputs = dict(C.BF.ROWS)
    r = C.BF.FIRST_ROW
    sections = sorted(wb.estimate.sections, key=lambda s: (s.display_order, s.name, s.id))
    placed = set()
    for sec in sections:
        members = [i for i in wb.items
                   if i.section_id == sec.id and section_of(wb, i) is sec]
        if not members:
            continue
        p.bid_sections.append(Row(row=r, kind="SECTION", id=sec.id, v=sec.v, obj=sec))
        r += 1
        for item in members:
            p.bid_rows[item.id] = Row(row=r, kind="ITEM_BID", id=item.id, v=item.v, obj=item)
            placed.add(item.id)
            r += 1
    rest = [i for i in wb.items if i.id not in placed]
    if rest and p.bid_sections:
        p.bid_sections.append(Row(row=r, kind="GROUP"))
        r += 1
    for item in rest:
        p.bid_rows[item.id] = Row(row=r, kind="ITEM_BID", id=item.id, v=item.v, obj=item)
        r += 1
    p.bid_items_span = (C.BF.FIRST_ROW, max(r - 1, C.BF.FIRST_ROW))
    r += 2   # a blank row, then the "Bid totals" heading at r - 1
    for total in _definitions(wb):
        p.bid_total_rows.append(Row(row=r, kind="BID_TOTAL", id=total.id, obj=total))
        r += 1


def _recap(p, wb):
    r = FIRST_ROW
    for item in wb.items:
        p.recap_rows[item.id] = r
        r += 1
    p.recap_total_row = r


def _holidays(calendar_conf):
    """The schedule's holidays as dates (a compact ``YYYYMMDD`` matches too)."""
    return {parse_iso_date(h) for h in calendar_conf.get("holidays") or ()}


def _working_day(calendar_conf, day, holidays=None):
    weekdays = calendar_conf.get("working_weekdays")
    if weekdays is not None and day.weekday() not in weekdays:
        return False
    return day not in (_holidays(calendar_conf) if holidays is None else holidays)


def _schedule(p, wb):
    dated = [a for a in wb.activities if a.start_date and a.finish_date]
    if not dated:
        return
    item_order = {i.id: n for n, i in enumerate(wb.items)}
    dated.sort(key=lambda a: (a.start_date, item_order[a.item_id], a.sort_order, a.id))
    r = FIRST_ROW
    for a in dated:
        p.schedule_rows[a.id] = r
        r += 1
    conf = wb.estimate.schedule
    first = min(date.fromisoformat(a.start_date) for a in dated)
    last = max(date.fromisoformat(a.finish_date) for a in dated)
    day, tail = first - timedelta(days=CALENDAR_LEAD_DAYS), 0
    holidays = _holidays(conf)
    while day <= last or tail < CALENDAR_TAIL_DAYS:
        if _working_day(conf, day, holidays):
            p.calendar.append(day)
            if day > last:
                tail += 1
        day += timedelta(days=1)
    monday = first - timedelta(days=first.weekday())
    end = last + timedelta(weeks=4)
    while monday <= end and len(p.weeks) < MAX_WEEKS:
        p.weeks.append(monday)
        monday += timedelta(weeks=1)


def _flat(p, wb):
    r = FIRST_ROW
    for row in p.cost_report:
        if row.kind != "ACTIVITY":
            continue
        a = row.obj
        if a.crew_id is not None:
            p.flat_rows.append(Row(row=r, kind="CREW_CHARGE", id=a.id, parent_id=a.id, obj=a))
            r += 1
        for res in wb.resources_of(a.id):
            p.flat_rows.append(Row(row=r, kind="RESOURCE", id=res.id, parent_id=a.id, obj=res))
            r += 1


def plan(wb, style) -> Plan:
    p = Plan(tabs={key: style.tab(key) for key in C.SHEETS})
    _cost_report(p, wb)
    _crews(p, wb)
    _rates(p, wb)
    _shares(p, wb)
    _bid_form(p, wb)
    _recap(p, wb)
    _schedule(p, wb)
    _flat(p, wb)
    _check_complete(p, wb)
    return p


def _check_complete(p, wb):
    """Every activity, resource and share's activity has a Cost Report row
    (``model.parse`` already refuses what would leave one out; this guards
    the formulas against a row-less reference)."""
    missing = next((f"activity {a.id}" for a in wb.activities if a.id not in p.activity_rows),
                   None)
    missing = missing or next((f"resource {r.id}" for r in wb.resources
                               if r.id not in p.resource_rows), None)
    missing = missing or next((f"share of activity {s.activity_id} to item {s.item_id}"
                               for s in wb.shares if s.activity_id not in p.activity_rows), None)
    if missing:
        raise PayloadError(f"{missing}: has no Cost Report row (orphaned activity?)")


def _row_kinds():
    """Which hidden cells identify each row kind (see the module docstring)."""
    cr = [
        ("ITEM", {"id": C.CR.ID, "v": C.CR.V}),
        ("ELEMENT_QTY", {"element_id": C.CR.ID, "quantity_key": C.CR.KEY, "v": C.CR.V}),
        ("ACTIVITY", {"id": C.CR.ID, "v": C.CR.V, "parent_id": C.CR.PARENT}),
        ("STEP", {"id": C.CR.ID, "v": C.CR.V, "activity_id": C.CR.PARENT}),
        ("RESOURCE", {"id": C.CR.ID, "v": C.CR.V, "activity_id": C.CR.PARENT}),
        ("STEPS", {"activity_id": C.CR.PARENT}),
        ("START", {"activity_id": C.CR.PARENT}),
        ("END", {"activity_id": C.CR.PARENT}),
        ("GROUP", {}),
    ]
    crews = [
        ("CREW", {"id": C.CW.ID, "v": C.CW.V}),
        ("MEMBER", {"id": C.CW.ID, "crew_id": C.CW.CREW}),
        ("NOTE", {"crew_id": C.CW.CREW}),
        ("CREW_END", {"crew_id": C.CW.CREW}),
    ]
    bid = [
        # The markup % row: the estimate's id/v, and its input name.
        ("ESTIMATE", {"id": C.BF.ID, "v": C.BF.V, "name": C.BF.INPUT}),
        ("BID_INPUT", {"name": C.BF.INPUT}),
        ("BID_FIGURE", {"name": C.BF.INPUT}),
        ("SECTION", {"id": C.BF.ID, "v": C.BF.V}),
        ("ITEM_BID", {"id": C.BF.ID, "v": C.BF.V}),
        ("BID_TOTAL", {"id": C.BF.ID}),
        ("GROUP", {}),
    ]
    return ([{"sheet": "cost_report", "kind": k, "kind_cell": C.CR.KIND, "identified_by": ids,
              "editable": k not in ("STEPS", "START", "END", "GROUP")} for k, ids in cr]
            + [{"sheet": "crews", "kind": k, "kind_cell": C.CW.KIND, "identified_by": ids,
                "editable": k in ("CREW", "MEMBER")} for k, ids in crews]
            + [{"sheet": "bid_form", "kind": k, "kind_cell": C.BF.KIND, "identified_by": ids,
                "editable": k in ("ESTIMATE", "BID_INPUT", "ITEM_BID")} for k, ids in bid])


def layout_json(p, wb, style, baseline) -> dict:
    """What ``_wb!A1`` carries: the format, the column letters, how each row
    kind is identified, and ``baseline`` -- how the payload the book was
    built from is stored in ``_wb`` column B (``baseline.encode``'s meta).
    Its size does not grow with the estimate (Excel caps a cell at 32,767
    characters)."""
    return {
        "format": FORMAT_NAME, "layout_version": LAYOUT_VERSION,
        "style": {"name": style.name, "version": style.version},
        "estimate_id": wb.estimate.id, "estimate_v": wb.estimate.v,
        "tabs": dict(p.tabs),
        "columns": {key: {c.key: c.letter for c in cols} for key, cols in C.SHEETS.items()},
        "first_row": FIRST_ROW,
        # The estimate rows are found by their name in ``name_cell`` (on an
        # ESTIMATE, BID_INPUT or BID_FIGURE row); the value is in
        # ``value_cell``. ``inputs`` are editable, ``figures`` derived.
        "bid_inputs": {"name_cell": C.BF.INPUT, "value_cell": C.BF.VALUE,
                       "inputs": [n for n in C.BF.ROWS if n in C.BF.INPUTS],
                       "figures": [n for n in C.BF.ROWS if n not in C.BF.INPUTS]},
        "row_kinds": _row_kinds(),
        "baseline": dict(baseline),
    }
