"""BidSheet.ai's estimate workbook payload, parsed and checked.

``parse(doc)`` turns the ``get_estimate_workbook`` JSON into frozen
dataclasses and refuses a payload the workbook cannot be built from: a
missing section, an editable row without its ``id``/``v``, a value that is
not a number where one is required, a count that is not an integer, a row
that is not an object, a non-finite number (NaN, Infinity), a duplicate id
(per section; steps and crew members across the payload), a duplicate
quantity key within an element, a reference to a row the payload
does not carry, an id that is not an integer or string (a schedule or bid
total id, which formulas embed, must be an integer), or a date outside
``DATE_YEARS``. Any other malformed row is refused naming its section and
index -- never a bare KeyError/TypeError. The payload has no version field,
so this shape check is the guard against a changed format.

An activity's crew may legitimately be absent (the read leaves out crews the
estimate may not use); ``Workbook.crew(id)`` then returns None and the
workbook shows that crew's cost as of export.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

SECTIONS = ("estimate", "items", "elements", "activities", "resources", "crews",
            "rates", "shares")


class PayloadError(ValueError):
    """The payload cannot be rendered; the message names the row and field."""


def _dec(value, where):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise PayloadError(f"{where}: expected a number, got {value!r}")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise PayloadError(f"{where}: expected a number, got {value!r}") from None
    if not number.is_finite():
        raise PayloadError(f"{where}: expected a finite number, got {value!r}")
    return number


def _req(row, key, where):
    if key not in row:
        raise PayloadError(f"{where}: missing {key!r}")
    return row[key]


def _id(value, where, *, nullable=False):
    """A row id or a reference to one: an integer or a string (never a bool,
    a float, a list or an object -- ids key dicts and land in cells)."""
    if value is None and nullable:
        return None
    if isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise PayloadError(f"{where}: expected an integer or string id, got {value!r}")


def _int_id(value, where):
    """An id written into a formula (a schedule or bid total id): an integer
    or null, never anything that could be formula text."""
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise PayloadError(f"{where}: expected an integer, got {value!r}")


def _schedule_ids(value, where):
    """``schedule_ids``: null (every schedule) or a list of integer ids."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise PayloadError(f"{where}: expected null or a list of integers, got {value!r}")
    for k, sid in enumerate(value):
        if sid is None:
            raise PayloadError(f"{where}[{k}]: expected an integer, got None")
        _int_id(sid, f"{where}[{k}]")
    return tuple(value)


def _row_id_v(row, where):
    return _id(_req(row, "id", where), f"{where}.id"), _req(row, "v", where)


def _int(value, where, default=0):
    """An integer field (counts, orders): an int or an integer string."""
    if value is None or value == "":
        return default
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    raise PayloadError(f"{where}: expected an integer, got {value!r}")


def _list(value, where):
    """A list of objects (a section, or a row's nested rows)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise PayloadError(f"{where}: expected a list, got {type(value).__name__}")
    for n, row in enumerate(value):
        if not isinstance(row, dict):
            raise PayloadError(f"{where}[{n}]: expected an object, got {type(row).__name__}")
    return value


#: The years a payload date may fall in: the schedule's working-day calendar
#: runs from a week before the earliest start to years past the last finish,
#: and Excel has no dates before 1900.
DATE_YEARS = (1900, 2200)


def parse_iso_date(value):
    """``YYYY-MM-DD`` or compact ``YYYYMMDD`` as a date. ``date.fromisoformat``
    only accepts the compact form from Python 3.11, so it is parsed here."""
    if len(value) == 8 and value.isdigit():
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return date.fromisoformat(value)


def _iso_date(value, where):
    """An ISO date string or null, returned as ``YYYY-MM-DD`` (a compact
    ``YYYYMMDD`` is normalised, so dates compare as strings). Years outside
    ``DATE_YEARS`` are refused."""
    if value is None:
        return None
    day = None
    if isinstance(value, str):
        try:
            day = parse_iso_date(value)
        except ValueError:
            pass
    if day is None:
        raise PayloadError(f"{where}: expected an ISO date (YYYY-MM-DD) or null, got {value!r}")
    if not DATE_YEARS[0] <= day.year <= DATE_YEARS[1]:
        raise PayloadError(f"{where}: {value!r} is outside the years {DATE_YEARS[0]}-"
                           f"{DATE_YEARS[1]}")
    return day.isoformat()


def _schedule(value, where):
    """``estimate.schedule``: ``{start_date, working_weekdays, holidays}``.
    ``working_weekdays`` is null (every day works) or a non-empty list of
    weekdays 0 (Mon)..6 -- an empty or out-of-range list would leave no
    working day, and the calendar would never end."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PayloadError(f"{where}: expected an object, got {type(value).__name__}")
    out = dict(value)
    if "start_date" in out:
        out["start_date"] = _iso_date(value.get("start_date"), f"{where}.start_date")
    weekdays = value.get("working_weekdays")
    if weekdays is not None:
        if (not isinstance(weekdays, list) or not weekdays
                or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6
                       for d in weekdays)):
            raise PayloadError(f"{where}.working_weekdays: expected null or a non-empty list "
                               f"of weekdays 0 (Mon)..6, got {weekdays!r}")
    holidays = value.get("holidays")
    if holidays is not None:
        if not isinstance(holidays, list):
            raise PayloadError(f"{where}.holidays: expected a list of ISO dates, "
                               f"got {holidays!r}")
        for n, day in enumerate(holidays):
            if day is None:
                raise PayloadError(f"{where}.holidays[{n}]: expected an ISO date, got None")
        out["holidays"] = [_iso_date(day, f"{where}.holidays[{n}]")
                           for n, day in enumerate(holidays)]
    return out


@contextmanager
def _guard(where):
    """Turn any other failure while reading a row into a PayloadError that
    names the row."""
    try:
        yield
    except PayloadError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PayloadError(f"{where}: malformed row ({type(exc).__name__}: {exc})") from None


@dataclass(frozen=True)
class BidTotal:
    id: int | None
    name: str
    schedule_ids: tuple | None
    includes_unscheduled: bool
    is_primary: bool
    display_order: int
    amount: Decimal | None


#: ``bid_totals.IMPLICIT``: the one primary total of an estimate with no
#: bid total definitions (no amount to compare: the payload carried none).
IMPLICIT_TOTAL = BidTotal(id=None, name="Bid Total", schedule_ids=None,
                          includes_unscheduled=True, is_primary=True, display_order=0,
                          amount=None)


@dataclass(frozen=True)
class Section:
    id: int
    name: str
    schedule_id: int | None
    display_order: int
    v: str


@dataclass(frozen=True)
class Estimate:
    id: int
    name: str
    project_title: str
    markup_percentage: Decimal
    markup_amount: Decimal
    indirect_cost: Decimal
    bid_factor: Decimal
    live_bid_factor: Decimal
    excluded_cost: Decimal | None
    total_estimated_cost: Decimal
    markup_total: Decimal
    direct_cost: Decimal
    bid_totals: tuple
    sections: tuple
    schedule: dict
    v: str


@dataclass(frozen=True)
class Item:
    id: int
    item_number: str
    item_code: str
    description: str
    unit: str
    schedule_id: int | None
    schedule_label: str
    schedule_quantity: Decimal | None
    quantity_override: Decimal | None
    quantity: Decimal | None
    estimated_unit_price: Decimal | None
    calculated_unit_price: Decimal | None
    total: Decimal | None
    bid_unit_price: Decimal | None
    bid_unit_price_override: Decimal | None
    bid_total: Decimal | None
    scope: str
    scope_note: str
    section_id: int | None
    v: str


@dataclass(frozen=True)
class Quantity:
    element_id: int
    key: str
    label: str
    unit: str
    derived: Decimal | None
    override: Decimal | None
    effective: Decimal | None
    pay_item_id: int | None
    v: str


@dataclass(frozen=True)
class Element:
    id: int
    name: str
    element_type: str
    display_order: int
    quantities: tuple
    v: str


@dataclass(frozen=True)
class Step:
    id: int
    name: str
    duration: Decimal | None
    duration_unit: str
    sort_order: int
    v: str


@dataclass(frozen=True)
class Activity:
    id: int
    parent_id: int | None
    item_id: int
    assembly_type: str
    name: str
    description: str
    count: int
    sort_order: int
    production_rate: Decimal | None
    production_unit: str | None
    hours_per_shift: Decimal | None
    crew_factor: Decimal | None
    duration_shifts: Decimal | None
    basis_quantity: Decimal | None
    basis_unit: str
    basis_source_measure: str
    code: str
    crew_id: int | None
    steps: tuple
    cost: Decimal
    cost_split: dict
    manhours: Decimal
    start_date: str | None
    finish_date: str | None
    end_date: str | None
    duration_days: Decimal | None
    warnings: tuple
    v: str


@dataclass(frozen=True)
class Resource:
    id: int
    activity_id: int
    component_type: str
    name: str
    quantity: Decimal | None
    unit: str
    unit_cost: Decimal | None
    time_value: Decimal | None
    time_unit: str
    includes_burden: bool
    burden_percentage: Decimal | None
    labor_cost_basis: str
    sort_order: int
    cost: Decimal
    managed_by: str | None
    labor_rate_id: int | None
    equipment_rate_id: int | None
    material_cost_id: int | None
    v: str

    @property
    def rate_link(self):
        """The library rate this line was priced from, as the Cost Report's
        hidden AE cell carries it: ``labor:<id>``, ``equipment:<id>`` or
        ``material:<id>`` -- labour first, then equipment, then material --
        or None when the line is unlinked."""
        for kind, rid in (("labor", self.labor_rate_id), ("equipment", self.equipment_rate_id),
                          ("material", self.material_cost_id)):
            if rid not in (None, ""):
                return f"{kind}:{rid}"
        return None


@dataclass(frozen=True)
class Member:
    id: int
    classification: str
    count: Decimal
    labor_rate_id: int | None
    hourly_rate_override: Decimal | None
    effective_hourly_rate: Decimal
    sort_order: int


@dataclass(frozen=True)
class Crew:
    id: int
    name: str
    code: str
    scope: str
    hours_per_shift: Decimal
    crew_factor: Decimal
    hourly_rate: Decimal
    members: tuple
    v: str


@dataclass(frozen=True)
class Rate:
    kind: str
    id: int
    name: str
    unit: str
    rate: Decimal | None


@dataclass(frozen=True)
class Share:
    activity_id: int
    item_id: int
    element_id: int | None
    fraction: Decimal
    cost: Decimal
    manhours: Decimal


@dataclass(frozen=True)
class Workbook:
    estimate: Estimate
    items: tuple
    elements: tuple
    activities: tuple
    resources: tuple
    crews: tuple
    rates: tuple
    shares: tuple
    source_sha: str

    # Id maps, built once (``parse`` refuses duplicate ids, so each is exact).
    @functools.cached_property
    def _items_by_id(self):
        return {i.id: i for i in self.items}

    @functools.cached_property
    def _activities_by_id(self):
        return {a.id: a for a in self.activities}

    @functools.cached_property
    def _crews_by_id(self):
        return {c.id: c for c in self.crews}

    def item(self, item_id):
        return self._items_by_id.get(item_id)

    def activity(self, activity_id):
        return self._activities_by_id.get(activity_id)

    def crew(self, crew_id):
        return self._crews_by_id.get(crew_id)

    def rates_by_kind(self, kind):
        return tuple(r for r in self.rates if r.kind == kind)

    def children(self, activity_id):
        kids = [a for a in self.activities if a.parent_id == activity_id]
        return tuple(sorted(kids, key=lambda a: (a.sort_order, a.id)))

    def roots(self, item_id):
        roots = [a for a in self.activities if a.item_id == item_id and a.parent_id is None]
        return tuple(sorted(roots, key=lambda a: (a.sort_order, a.id)))

    def resources_of(self, activity_id):
        rows = [r for r in self.resources if r.activity_id == activity_id]
        return tuple(sorted(rows, key=lambda r: (r.sort_order, r.id)))

    def shares_of_activity(self, activity_id):
        return tuple(s for s in self.shares if s.activity_id == activity_id)


def _estimate(doc):
    where = "estimate"
    eid, v = _row_id_v(doc, where)
    totals = doc.get("totals") or {}
    bid_totals = tuple(
        BidTotal(
            id=_int_id(bt.get("id"), f"{where}.bid_totals[{n}].id"),
            name=_req(bt, "name", f"{where}.bid_totals[{n}]"),
            schedule_ids=_schedule_ids(bt.get("schedule_ids"),
                                       f"{where}.bid_totals[{n}].schedule_ids"),
            includes_unscheduled=bool(bt.get("includes_unscheduled", True)),
            is_primary=bool(bt.get("is_primary", False)),
            display_order=_int(bt.get("display_order"), f"{where}.bid_totals[{n}].display_order"),
            amount=_dec(bt.get("amount"), f"{where}.bid_totals[{n}].amount"))
        for n, bt in enumerate(_list(_req(doc, "bid_totals", where), f"{where}.bid_totals")))
    if not bid_totals:
        # ``bid_totals.definitions``: an estimate with none set has one
        # implicit primary total over everything.
        bid_totals = (IMPLICIT_TOTAL,)
    sections = tuple(
        Section(id=_id(_req(s, "id", f"{where}.sections[{n}]"), f"{where}.sections[{n}].id"),
                name=_req(s, "name", f"{where}.sections[{n}]"),
                schedule_id=_int_id(s.get("schedule_id"), f"{where}.sections[{n}].schedule_id"),
                display_order=_int(s.get("display_order"), f"{where}.sections[{n}].display_order"),
                v=_req(s, "v", f"{where}.sections[{n}]"))
        for n, s in enumerate(_list(_req(doc, "sections", where), f"{where}.sections")))
    project = doc.get("project") or {}
    return Estimate(
        id=eid, name=doc.get("name") or "", project_title=project.get("title") or "",
        markup_percentage=_dec(doc.get("markup_percentage"), f"{where}.markup_percentage") or Decimal(0),
        markup_amount=_dec(doc.get("markup_amount"), f"{where}.markup_amount") or Decimal(0),
        indirect_cost=_dec(totals.get("indirect_cost"), f"{where}.totals.indirect_cost") or Decimal(0),
        bid_factor=_dec(_req(doc, "bid_factor", where), f"{where}.bid_factor"),
        live_bid_factor=_dec(doc.get("live_bid_factor"), f"{where}.live_bid_factor"),
        excluded_cost=_dec(doc.get("excluded_cost"), f"{where}.excluded_cost"),
        total_estimated_cost=_dec(totals.get("total_estimated_cost"),
                                  f"{where}.totals.total_estimated_cost") or Decimal(0),
        markup_total=_dec(totals.get("markup_total"), f"{where}.totals.markup_total") or Decimal(0),
        direct_cost=_dec(totals.get("direct_cost"), f"{where}.totals.direct_cost") or Decimal(0),
        bid_totals=bid_totals, sections=sections,
        schedule=_schedule(doc.get("schedule"), f"{where}.schedule"),
        v=v)


def _item(row, n):
    where = f"items[{n}]"
    iid, v = _row_id_v(row, where)
    schedule = row.get("schedule") or {}
    if not isinstance(schedule, dict):
        raise PayloadError(f"{where}.schedule: expected an object or null, "
                           f"got {type(schedule).__name__}")
    d = lambda key: _dec(row.get(key), f"{where}.{key}")  # noqa: E731
    return Item(
        id=iid, item_number=str(row.get("item_number") or ""),
        item_code=row.get("item_code") or "", description=row.get("description") or "",
        unit=row.get("unit") or "",
        schedule_id=_int_id(schedule.get("id"), f"{where}.schedule.id"),
        schedule_label=schedule.get("label") or schedule.get("name") or "",
        schedule_quantity=d("schedule_quantity"), quantity_override=d("quantity_override"),
        quantity=d("quantity"), estimated_unit_price=d("estimated_unit_price"),
        calculated_unit_price=d("calculated_unit_price"), total=d("total"),
        bid_unit_price=d("bid_unit_price"), bid_unit_price_override=d("bid_unit_price_override"),
        bid_total=d("bid_total"), scope=_req(row, "scope", where),
        scope_note=row.get("scope_note") or "",
        section_id=_id(row.get("section_id"), f"{where}.section_id", nullable=True), v=v)


def _element(row, n):
    where = f"elements[{n}]"
    eid, v = _row_id_v(row, where)
    quantities = []
    for k, q in enumerate(_list(_req(row, "quantities", where), f"{where}.quantities")):
        qw = f"{where}.quantities[{k}]"
        quantities.append(Quantity(
            element_id=eid, key=_req(q, "key", qw), label=q.get("label") or q["key"],
            unit=q.get("unit") or "", derived=_dec(q.get("derived"), f"{qw}.derived"),
            override=_dec(q.get("override"), f"{qw}.override"),
            effective=_dec(q.get("effective"), f"{qw}.effective"),
            pay_item_id=_id(q.get("pay_item_id"), f"{qw}.pay_item_id", nullable=True), v=_req(q, "v", qw)))
    return Element(id=eid, name=row.get("name") or "", element_type=row.get("element_type") or "",
                   display_order=_int(row.get("display_order"), f"{where}.display_order"),
                   quantities=tuple(quantities), v=v)


def _activity(row, n):
    where = f"activities[{n}]"
    aid, v = _row_id_v(row, where)
    d = lambda key: _dec(row.get(key), f"{where}.{key}")  # noqa: E731
    steps = tuple(
        Step(id=_id(_req(s, "id", f"{where}.steps[{k}]"), f"{where}.steps[{k}].id"), name=s.get("name") or "",
             duration=_dec(s.get("duration"), f"{where}.steps[{k}].duration"),
             duration_unit=s.get("duration_unit") or "DAYS",
             sort_order=_int(s.get("sort_order"), f"{where}.steps[{k}].sort_order"),
             v=_req(s, "v", f"{where}.steps[{k}]"))
        for k, s in enumerate(_list(row.get("steps"), f"{where}.steps")))
    code = (row.get("activity_code") or {}).get("code") or ""
    split = {k: _dec(val, f"{where}.cost_split.{k}") for k, val in (row.get("cost_split") or {}).items()}
    return Activity(
        id=aid, parent_id=_id(row.get("parent_id"), f"{where}.parent_id", nullable=True),
        item_id=_id(_req(row, "estimate_item_id", where), f"{where}.estimate_item_id"),
        assembly_type=row.get("assembly_type") or "", name=row.get("name") or "",
        description=row.get("description") or "", count=_int(row.get("count"), f"{where}.count", 1),
        sort_order=_int(row.get("sort_order"), f"{where}.sort_order"),
        production_rate=d("production_rate"),
        production_unit=row.get("production_unit"), hours_per_shift=d("hours_per_shift"),
        crew_factor=d("crew_factor"), duration_shifts=d("duration_shifts"),
        basis_quantity=d("basis_quantity"), basis_unit=row.get("basis_unit") or "",
        basis_source_measure=row.get("basis_source_measure") or "", code=code,
        crew_id=_id(row.get("crew_id"), f"{where}.crew_id", nullable=True), steps=tuple(sorted(steps, key=lambda s: (s.sort_order, s.id))),
        cost=d("cost") or Decimal(0), cost_split=split, manhours=d("manhours") or Decimal(0),
        start_date=_iso_date(row.get("start_date"), f"{where}.start_date"),
        finish_date=_iso_date(row.get("finish_date"), f"{where}.finish_date"),
        end_date=_iso_date(row.get("end_date"), f"{where}.end_date"),
        duration_days=d("duration_days"),
        warnings=tuple(str(w) for w in (row.get("warnings") or ())), v=v)


def _resource(row, n):
    where = f"resources[{n}]"
    rid, v = _row_id_v(row, where)
    d = lambda key: _dec(row.get(key), f"{where}.{key}")  # noqa: E731
    return Resource(
        id=rid, activity_id=_id(_req(row, "activity_id", where), f"{where}.activity_id"),
        component_type=row.get("component_type") or "other", name=row.get("name") or "",
        quantity=d("quantity"), unit=row.get("unit") or "", unit_cost=d("unit_cost"),
        time_value=d("time_value"), time_unit=row.get("time_unit") or "",
        # Component.includes_burden defaults to False.
        includes_burden=bool(row.get("includes_burden", False)),
        burden_percentage=d("burden_percentage"),
        labor_cost_basis=row.get("labor_cost_basis") or "production",
        sort_order=_int(row.get("sort_order"), f"{where}.sort_order"),
        cost=d("cost") or Decimal(0), managed_by=row.get("managed_by"),
        labor_rate_id=_id(row.get("labor_rate_id"), f"{where}.labor_rate_id", nullable=True),
        equipment_rate_id=_id(row.get("equipment_rate_id"), f"{where}.equipment_rate_id",
                              nullable=True),
        material_cost_id=_id(row.get("material_cost_id"), f"{where}.material_cost_id",
                             nullable=True),
        v=v)


def _crew(row, n):
    where = f"crews[{n}]"
    cid, v = _row_id_v(row, where)
    members = tuple(
        Member(id=_id(_req(m, "id", f"{where}.members[{k}]"), f"{where}.members[{k}].id"),
               classification=m.get("classification") or "",
               count=_dec(m.get("count"), f"{where}.members[{k}].count") or Decimal(0),
               labor_rate_id=_id(m.get("labor_rate_id"),
                                 f"{where}.members[{k}].labor_rate_id", nullable=True),
               hourly_rate_override=_dec(m.get("hourly_rate_override"),
                                         f"{where}.members[{k}].hourly_rate_override"),
               effective_hourly_rate=_dec(m.get("effective_hourly_rate"),
                                          f"{where}.members[{k}].effective_hourly_rate") or Decimal(0),
               sort_order=_int(m.get("sort_order"), f"{where}.members[{k}].sort_order"))
        for k, m in enumerate(_list(row.get("members"), f"{where}.members")))
    return Crew(id=cid, name=row.get("name") or "", code=row.get("code") or "",
                scope=_req(row, "scope", where),
                hours_per_shift=_dec(row.get("hours_per_shift"), f"{where}.hours_per_shift") or Decimal(8),
                crew_factor=_dec(row.get("crew_factor"), f"{where}.crew_factor") or Decimal(1),
                hourly_rate=_dec(row.get("hourly_rate"), f"{where}.hourly_rate") or Decimal(0),
                members=members, v=v)


def _rates(doc):
    if not isinstance(doc, dict):
        raise PayloadError(f"rates: expected an object, got {type(doc).__name__}")
    out = []
    for kind, value_key in (("labor", "rate"), ("equipment", "rate"), ("material", "cost")):
        for k, row in enumerate(_list(doc.get(kind), f"rates.{kind}")):
            where = f"rates.{kind}[{k}]"
            with _guard(where):
                out.append(Rate(
                    kind=kind, id=_id(_req(row, "id", where), f"{where}.id"),
                    name=(row.get("classification") or row.get("name")
                          or row.get("description") or ""),
                    unit=row.get("unit") or "",
                    rate=_dec(row.get(value_key), f"{where}.{value_key}")))
    return tuple(out)


def _share(row, n):
    where = f"shares[{n}]"
    return Share(activity_id=_id(_req(row, "activity_id", where), f"{where}.activity_id"),
                 item_id=_id(_req(row, "item_id", where), f"{where}.item_id"),
                 element_id=_id(row.get("element_id"), f"{where}.element_id", nullable=True),
                 fraction=_dec(_req(row, "fraction", where), f"{where}.fraction"),
                 cost=_dec(row.get("cost"), f"{where}.cost") or Decimal(0),
                 manhours=_dec(row.get("manhours"), f"{where}.manhours") or Decimal(0))


def _unique(where, ids):
    seen = set()
    for rid in ids:
        if rid in seen:
            raise PayloadError(f"{where}: duplicate id {rid!r}")
        seen.add(rid)


def _check_unique_ids(wb):
    """Ids are unique per section; step and crew member ids across the whole
    payload (they are rows of one table each); quantity keys within an
    element (a key identifies its quantity row)."""
    for section in ("items", "elements", "activities", "resources", "crews"):
        _unique(section, (row.id for row in getattr(wb, section)))
    _unique("activities.steps", (s.id for a in wb.activities for s in a.steps))
    _unique("crews.members", (m.id for c in wb.crews for m in c.members))
    for e in wb.elements:
        keys = [q.key for q in e.quantities]
        dup = next((k for n, k in enumerate(keys) if k in keys[:n]), None)
        if dup is not None:
            raise PayloadError(f"elements: element {e.id} has a duplicate quantity key {dup!r}")


def _check_parent_chains(wb):
    """Each activity's ``parent_id`` chain ends at a root, with no cycle
    (self-parent included), and a parent belongs to its child's item: the
    row plan walks children only under their parent's item, so an activity
    in either case would get no row."""
    by_id = {a.id: a for a in wb.activities}
    for a in wb.activities:
        if a.parent_id is not None and by_id[a.parent_id].item_id != a.item_id:
            raise PayloadError(f"activity {a.id}: parent {a.parent_id} is on item "
                               f"{by_id[a.parent_id].item_id}, not on its own item {a.item_id}")
        seen = {a.id}
        node = a
        while node.parent_id is not None:
            if node.parent_id in seen:
                raise PayloadError(f"activity {a.id}: parent cycle")
            seen.add(node.parent_id)
            node = by_id[node.parent_id]


def _check_references(wb):
    item_ids = {i.id for i in wb.items}
    activity_ids = {a.id for a in wb.activities}
    for a in wb.activities:
        if a.item_id not in item_ids:
            raise PayloadError(f"activity {a.id}: item {a.item_id} is not in the payload")
        if a.parent_id is not None and a.parent_id not in activity_ids:
            raise PayloadError(f"activity {a.id}: parent {a.parent_id} is not in the payload")
    _check_parent_chains(wb)
    for r in wb.resources:
        if r.activity_id not in activity_ids:
            raise PayloadError(f"resource {r.id}: activity {r.activity_id} is not in the payload")
    for e in wb.elements:
        for q in e.quantities:
            if q.pay_item_id is not None and q.pay_item_id not in item_ids:
                raise PayloadError(f"element {e.id} {q.key}: pays item {q.pay_item_id}, "
                                   "which is not in the payload")
    for s in wb.shares:
        if s.item_id not in item_ids:
            raise PayloadError(f"share of activity {s.activity_id}: item {s.item_id} "
                               "is not in the payload")
        if s.activity_id not in activity_ids:
            raise PayloadError(f"share to item {s.item_id}: activity {s.activity_id} "
                               "is not in the payload")


def source_sha(doc) -> str:
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_PAGED = ("items", "activities", "resources", "elements", "crews")


def _id_key(value):
    """A total order over ids of any JSON type (ints first, numerically)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return (0, value, "")
    return (1, 0, json.dumps(value, sort_keys=True, default=str))


def _item_order_key(row):
    """``EstimateItem.objects.order_by_item_number_numeric``: the leading
    digits of the item number left-padded to 6 (none: "999999"), then the
    item number, then the item code -- and the id, so ties are stable."""
    number = str(row.get("item_number") or "")
    digits = re.match(r"[0-9]*", number).group(0) or "999999"
    return (digits.rjust(6, "0")[:6], number, str(row.get("item_code") or ""),
            _id_key(row.get("id")))


def _merge_order(merged):
    """Order merged rows the way one whole payload orders them, whatever
    order the pages came in: items by item number (``_item_rows``),
    activities by (item id, sort order, id) (``_item_assemblies``),
    resources under their activity by (sort order, id), elements by
    (display order, id)."""
    merged["items"].sort(key=_item_order_key)
    merged["activities"].sort(key=lambda a: (
        _id_key(a.get("estimate_item_id")),
        _int(a.get("sort_order"), f"activity {a.get('id')!r}: sort_order"),
        _id_key(a.get("id"))))
    at = {json.dumps(a.get("id"), default=str): n for n, a in enumerate(merged["activities"])}
    merged["resources"].sort(key=lambda r: (
        at.get(json.dumps(r.get("activity_id"), default=str), len(at)),
        _int(r.get("sort_order"), f"resource {r.get('id')!r}: sort_order"),
        _id_key(r.get("id"))))
    merged["elements"].sort(key=lambda e: (
        _int(e.get("display_order"), f"element {e.get('id')!r}: display_order"),
        _id_key(e.get("id"))))


def _page_key(doc):
    """Pages hold disjoint items, so their item order is a page order that
    does not depend on the order the pages were given in."""
    return (sorted(_item_order_key(i) for i in doc.get("items") or ()),
            json.dumps(doc, sort_keys=True, default=str))


def _check_page(n, doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("estimate"), dict):
        raise PayloadError(f"page {n}: not a get_estimate_workbook payload")
    for key in _PAGED + ("shares",):
        _list(doc.get(key), f"page {n}: {key}")
    rates = doc.get("rates")
    if rates is None:
        return
    if not isinstance(rates, dict):
        raise PayloadError(f"page {n}: rates: expected an object, got {type(rates).__name__}")
    for kind, rows in rates.items():
        _list(rows, f"page {n}: rates.{kind}")


def merge_pages(docs):
    """One payload from ``get_estimate_workbook`` pages (``item_ids``).

    Every page carries the whole ``estimate`` block, and it must be the same
    on every page -- else the estimate changed between fetches and the
    pages must be fetched again. Row sections are concatenated and
    de-duplicated by id; a row that appears on two pages must be identical,
    for the same reason. Rates are de-duplicated per kind by id and shares
    by (activity, item, element); a conflicting duplicate is refused too.
    The result is ordered as one whole payload would be, so it does not
    depend on the order the pages are given in."""
    docs = list(docs)
    if not docs:
        raise PayloadError("no payload pages given")
    if len(docs) == 1:
        return docs[0]
    for n, doc in enumerate(docs, start=1):
        _check_page(n, doc)
    first = docs[0]["estimate"]
    for n, doc in enumerate(docs[1:], start=2):
        if doc["estimate"].get("id") != first.get("id"):
            raise PayloadError(f"page {n}: estimate {doc['estimate'].get('id')} is not "
                               f"estimate {first.get('id')} (pages must come from one estimate)")
        if doc["estimate"] != first:
            raise PayloadError(f"page {n}: estimate changed between fetches; re-fetch "
                               "every page")
    docs.sort(key=_page_key)

    def keep(seen, key, row, what):
        if key in seen:
            if seen[key] != row:
                raise PayloadError(f"{what} differs between pages -- it changed between "
                                   "fetches; re-fetch")
            return False
        seen[key] = row
        return True

    merged = {"estimate": first}
    for key in _PAGED:
        seen, rows = {}, []
        for doc in docs:
            for row in doc.get(key) or ():
                rid = json.dumps(row.get("id"), sort_keys=True, default=str)
                if keep(seen, rid, row, f"{key} row {row.get('id')!r}"):
                    rows.append(row)
        merged[key] = rows
    rates = {}
    for doc in docs:
        for kind, rows in (doc.get("rates") or {}).items():
            bucket = rates.setdefault(kind, {})
            for row in rows or ():
                keep(bucket, json.dumps(row.get("id"), sort_keys=True, default=str), row,
                     f"rates.{kind} row {row.get('id')!r}")
    merged["rates"] = {kind: sorted(rows.values(), key=lambda r: _id_key(r.get("id")))
                       for kind, rows in sorted(rates.items())}
    shares = {}
    for doc in docs:
        for s in doc.get("shares") or ():
            key = json.dumps([s.get("activity_id"), s.get("item_id"), s.get("element_id")],
                             sort_keys=True, default=str)
            keep(shares, key, s, f"share of activity {s.get('activity_id')!r} to item "
                                 f"{s.get('item_id')!r}")
    merged["shares"] = [shares[k] for k in sorted(shares)]
    _merge_order(merged)
    return merged


def parse(doc) -> Workbook:
    if not isinstance(doc, dict):
        raise PayloadError("the payload must be a JSON object")
    for key in SECTIONS:
        if key not in doc:
            raise PayloadError(f"the payload has no {key!r} section "
                               "(is this a get_estimate_workbook response?)")
    if not isinstance(doc["estimate"], dict):
        raise PayloadError("estimate: expected an object")
    with _guard("estimate"):
        estimate = _estimate(doc["estimate"])

    def section(name, parse_row):
        out = []
        for n, row in enumerate(_list(doc[name], name)):
            with _guard(f"{name}[{n}]"):
                out.append(parse_row(row, n))
        return tuple(out)

    wb = Workbook(
        estimate=estimate,
        items=section("items", _item),
        elements=section("elements", _element),
        activities=section("activities", _activity),
        resources=section("resources", _resource),
        crews=section("crews", _crew),
        rates=_rates(doc["rates"]),
        shares=section("shares", _share),
        source_sha=source_sha(doc))
    _check_unique_ids(wb)
    _check_references(wb)
    return wb
