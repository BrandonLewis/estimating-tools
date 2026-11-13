"""The read-model collections a template fill lays out on a ``display`` sheet
(and a ``rates`` sheet's sections), with their order and identity: the read
model's own arithmetic, kept here so no pack repeats it and no pack's code
is needed to fill a book (engine spec, "No hooks": what a declaration names
is the engine's).

A ``Source`` is a collection (``rows(wb, sheet)``, in the order a book lists
it), the read-model class its labels resolve against, the id a display row
stores (``ident``), the children a prototype's sample row is repeated for
(``children``: row kind -> class and collection), its variants (a predicate
per name, tried in the sheet's prototype order) and whether a change to its
set reprices the book (``priced``: a refresh reports it as structural). A
source with no ids (the calendar) is matched row by row, in order.

The orders are HeavyBook's, which are BidSheet.ai's: the activity tree
(items in payload order; each item's root activities by sort order and id,
depth first), element quantities by element display order then key, the
schedule by start, item, sort order and id, bid lines by section, bid totals
by display order. The working-day calendar runs from a week before the
first start to 260 working days past the last finish."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta

from estimating_tools.exchange import labels, model

__all__ = ["Cover", "child_ident", "FLAT", "MissingCrew", "RateSection", "SOURCES", "Source", "Warning",
           "Workday", "bid_lines", "bid_totals", "coverage", "primary_total", "quantities",
           "scheduled", "tree", "warning_ident", "working_days"]

CALENDAR_LEAD_DAYS = 7
CALENDAR_TAIL_DAYS = 260


@dataclass(frozen=True)
class Warning:
    """One of an activity's BidSheet.ai warnings."""
    activity: model.Activity
    text: str


def warning_ident(activity_id, text: str) -> str:
    """The id a warning's display row stores: its activity's id and a digest
    of its text. Content, not place: a warning BidSheet.ai removes takes
    only its own row with it (a place would shift every later row onto the
    next warning). Two alike warnings on one activity share the id and are
    matched in order."""
    digest = hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:10]
    return f"{activity_id}:{digest}"


@dataclass(frozen=True)
class MissingCrew:
    """A crew an activity names that the export does not carry."""
    id: int


@dataclass(frozen=True)
class Workday:
    day: date


@dataclass(frozen=True)
class Cover:
    """One schedule a bid total covers (``total_key`` ``T:<id>``; ``T:`` for
    the implicit total), and whether that total is the primary."""
    total_key: str
    schedule_id: int
    primary: bool
    name: str


@dataclass(frozen=True)
class RateSection:
    kind: str
    title: str


# A display class's own field that holds a read-model object is walked like
# a relation.
labels.NAV[(Warning, "activity")] = (model.Activity, lambda wb, w: w.activity)


def tree(wb) -> list:
    """Activities in the Cost Report's order."""
    out = []

    def walk(a):
        out.append(a)
        for child in wb.children(a.id):
            walk(child)
    for item in wb.items:
        for root in wb.roots(item.id):
            walk(root)
    return out


def quantities(wb) -> list:
    return [q for e in sorted(wb.elements, key=lambda e: (e.display_order, e.id))
            for q in sorted(e.quantities, key=lambda q: q.key)]


def bid_totals(wb) -> list:
    """``bid_totals.definitions``' order (the implicit total included)."""
    return sorted(wb.estimate.bid_totals,
                  key=lambda t: (t.display_order, -1 if t.id is None else t.id))


def primary_total(wb):
    """The primary total, else the first definition."""
    defs = bid_totals(wb)
    return next((t for t in defs if t.is_primary), defs[0] if defs else None)


def coverage(wb) -> list:
    """Per bid total, the schedules it sums: its listed ids, or every
    schedule an item is on when it lists none; ``-1`` (unscheduled items)
    when it includes them (``EstimateBidTotal.covers``)."""
    scheduled_ids = sorted({i.schedule_id for i in wb.items if i.schedule_id is not None})
    primary = primary_total(wb)
    out = []
    for t in bid_totals(wb):
        ids = list(t.schedule_ids) if t.schedule_ids is not None else list(scheduled_ids)
        if t.includes_unscheduled:
            ids.append(-1)
        key = f"T:{'' if t.id is None else t.id}"
        out += [Cover(key, int(sid), t is primary, t.name) for sid in ids]
    return out


def scheduled(wb) -> list:
    """Dated activities, by start, then item order, sort order and id."""
    order = {i.id: n for n, i in enumerate(wb.items)}
    dated = [a for a in wb.activities if a.start_date and a.finish_date]
    return sorted(dated, key=lambda a: (a.start_date, order[a.item_id], a.sort_order, a.id))


def _working(conf, day, holidays) -> bool:
    weekdays = conf.get("working_weekdays")
    if weekdays is not None and day.weekday() not in weekdays:
        return False
    return day not in holidays


def working_days(wb) -> list:
    dated = scheduled(wb)
    if not dated:
        return []
    conf = wb.estimate.schedule
    holidays = {model.parse_iso_date(h) for h in conf.get("holidays") or ()}
    first = min(date.fromisoformat(a.start_date) for a in dated)
    last = max(date.fromisoformat(a.finish_date) for a in dated)
    out, day, tail = [], first - timedelta(days=CALENDAR_LEAD_DAYS), 0
    while day <= last or tail < CALENDAR_TAIL_DAYS:
        if _working(conf, day, holidays):
            out.append(Workday(day))
            if day > last:
                tail += 1
        day += timedelta(days=1)
    return out


def bid_lines(wb) -> list:
    """The Bid Form's item rows: each section (display order, name, id) with
    its items, then -- when there were sections -- a GROUP row and the rest:
    ``[(kind, object)]``."""
    out, placed = [], set()
    for sec in sorted(wb.estimate.sections, key=lambda s: (s.display_order, s.name, s.id)):
        members = [i for i in wb.items
                   if i.section_id == sec.id and model.section_of(wb, i) is sec]
        if not members:
            continue
        out.append(("SECTION", sec))
        for item in members:
            out.append(("ITEM_BID", item))
            placed.add(item.id)
    rest = [i for i in wb.items if i.id not in placed]
    if rest and out:
        out.append(("GROUP", None))
    out += [("ITEM_BID", i) for i in rest]
    return out


def child_ident(obj):
    """The id a source's child row stores: a library rate's link (a rate's
    own id repeats across rate kinds), else the child's id."""
    if isinstance(obj, model.Rate):
        return obj.link
    return getattr(obj, "id", None)


def _missing_crews(wb):
    return [MissingCrew(c) for c in sorted({a.crew_id for a in wb.activities
                                             if a.crew_id is not None and wb.crew(a.crew_id) is None})]


def _unshifted(wb):
    return [a for a in wb.activities if a.crew_id is not None and wb.crew(a.crew_id) is None
            and not a.steps and not a.duration_shifts]


@dataclass(frozen=True)
class Source:
    cls: type
    rows: object                                       # (wb, sheet) -> sequence
    ident: object = lambda obj: getattr(obj, "id", None)
    children: dict = field(default_factory=dict)       # row kind -> (class, (wb, obj) -> seq)
    variants: dict = field(default_factory=dict)       # name -> (wb, obj) -> bool
    priced: bool = False


def _share_id(s):
    return f"{s.activity_id}:{s.item_id}:{'' if s.element_id is None else s.element_id}"


SOURCES = {
    "ESTIMATE": Source(model.Estimate, lambda wb, s: [wb.estimate]),
    "ITEM": Source(model.Item, lambda wb, s: list(wb.items),
                   variants={"excluded": lambda wb, i: i.scope == "excluded"}),
    "ITEM_BID": Source(model.Item, lambda wb, s: list(wb.items)),
    "ELEMENT_QTY": Source(model.Quantity, lambda wb, s: quantities(wb),
                          ident=lambda q: f"{q.element_id}:{q.key}"),
    "ACTIVITY": Source(model.Activity, lambda wb, s: tree(wb),
                       children={"RESOURCE": (model.Resource,
                                              lambda wb, a: list(wb.resources_of(a.id)))},
                       variants={"stepped": lambda wb, a: bool(a.steps),
                                 "crew": lambda wb, a: a.crew_id is not None}),
    "RESOURCE": Source(model.Resource,
                       lambda wb, s: [r for a in tree(wb) for r in wb.resources_of(a.id)]),
    "CREW": Source(model.Crew, lambda wb, s: list(wb.crews)),
    "BID_TOTAL": Source(model.BidTotal, lambda wb, s: bid_totals(wb)),
    "SHARE": Source(model.Share, lambda wb, s: list(wb.shares), ident=_share_id, priced=True),
    "COVERAGE": Source(Cover, lambda wb, s: coverage(wb),
                       ident=lambda c: f"{c.total_key}:{c.schedule_id}", priced=True),
    "SCHEDULE": Source(model.Activity, lambda wb, s: scheduled(wb)),
    "WARNING": Source(Warning, lambda wb, s: [Warning(a, w) for a in wb.activities
                                              for w in a.warnings],
                      ident=lambda w: warning_ident(w.activity.id, w.text)),
    "MISSING_CREW": Source(MissingCrew, lambda wb, s: _missing_crews(wb)),
    "NO_SHIFTS": Source(model.Activity, lambda wb, s: _unshifted(wb)),
    # Id-less: a refresh rewrites the calendar row by row, in order. Not
    # priced -- the Schedule's finishes look days up on it, so moved dates
    # are taken in place.
    "WORKDAY": Source(Workday, lambda wb, s: working_days(wb), ident=lambda d: None),
    "RATE_SECTION": Source(RateSection,
                           lambda wb, s: [RateSection(k, t) for k, t in s.sections.items()],
                           ident=lambda sec: sec.kind,
                           children={"RATE": (model.Rate,
                                              lambda wb, sec: list(wb.rates_by_kind(sec.kind)))}),
}

#: A flat sheet's regions: the row kinds a region lists -> its rows in
#: order, ``[(kind, object)]``.
FLAT = {
    ("SECTION", "ITEM_BID", "GROUP"): bid_lines,
    ("BID_TOTAL",): lambda wb: [("BID_TOTAL", t) for t in bid_totals(wb)],
}
