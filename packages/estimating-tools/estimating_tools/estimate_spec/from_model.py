"""Lay BidSheet.ai's estimate read model out as a fieldbook config.

``from_model(payload)`` returns the config dict the fieldbook renderer
consumes (``build.generate(config, pack, exchange=...)``). Every item is laid
out with the ``lump_sum`` recipe: the read model carries no takeoff, which is
what ``line_item`` would lay a band from.
"""
from __future__ import annotations

from decimal import Decimal

from estimating_tools.estimate_spec.build import literal, sheet_title
from estimating_tools.exchange import model as M

_TIMED = ("labor", "equipment")
_COMPONENT_TYPES = {"subcontractor": "subcontract"}
_ZERO_COSTS = ("labor", "equipment", "material", "subcontract")


class FromModelError(ValueError):
    """The read model cannot be laid out as a fieldbook."""


def _num(value):
    """A Decimal as the config writes it: an int when integral, else a float."""
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _amount(value):
    """A priced number (a quantity, count, time, rate or cost): 0 when the
    server sends null (R11) -- an unpriced row on a live estimate is
    ordinary, and 0 shows the gap on Checks."""
    return _num(Decimal(0) if value is None else value)


def _text(value) -> str:
    """Server text (a name, description or note) as literal text: shared
    server data never becomes a live formula (R14)."""
    return literal(value)


def _exchange(**tags) -> dict:
    """An ``exchange`` mapping without its None (or blank) values."""
    return {k: v for k, v in tags.items() if v is not None and v != ""}


def _markup(estimate) -> dict:
    fraction = _num(estimate.markup_percentage / 100)
    return {"overhead": dict.fromkeys(_ZERO_COSTS, fraction),
            "insurance": dict.fromkeys(_ZERO_COSTS, 0),
            "profit": dict.fromkeys(_ZERO_COSTS, 0), "bond_pct": 0}


def _who(act) -> str:
    return f"activity {act.id} ({act.name})"


def _refuse_unshowable(wb) -> None:
    """Fieldbook lays out top-level GENERIC activities without steps only."""
    for act in wb.activities:
        if act.parent_id is not None:
            why = f"has a parent (activity {act.parent_id})"
        elif act.assembly_type != "GENERIC":
            why = f"is a {act.assembly_type} activity"
        elif act.steps:
            why = "has steps"
        else:
            continue
        raise FromModelError(f"{_who(act)} {why}; fieldbook shows only top-level GENERIC "
                             "activities without steps")


def _shift_hours(wb) -> int | float:
    """The one shift length every activity shares; 8 when none states one."""
    prev = None
    for act in wb.activities:
        if act.hours_per_shift is None:
            continue
        if prev is not None and act.hours_per_shift != prev.hours_per_shift:
            raise FromModelError(
                f"shift hours differ: {_who(prev)} has {prev.hours_per_shift} and "
                f"{_who(act)} has {act.hours_per_shift}; fieldbook has one shift length")
        prev = act
    return _num(prev.hours_per_shift) if prev else 8


def _is_timed(res) -> bool:
    return res.component_type in _TIMED and res.time_value is not None


def _library_ref(res, library) -> str | None:
    """``labor:<id>`` / ``equipment:<id>`` when the rate is in the library."""
    rid = res.labor_rate_id if res.component_type == "labor" else res.equipment_rate_id
    ref = f"{res.component_type}:{rid}" if rid is not None else None
    return ref if ref in library else None


def _library_names(rates) -> dict[str, str]:
    """A name per library rate, unique within the estimate, by link.

    Crew rows find their rate by name (a VLOOKUP over the rate table), so two
    rates sharing a name (one trade under two unions, or a labor and an
    equipment rate) would both price as the first. The first rate keeps its
    name; the others take " (2)", " (3)"... ``rates`` come in (kind, id)
    order, not payload order, so a rebuild cannot swap the suffixes and
    repoint a crew row. Sync never reads these names: it goes by the ref."""
    taken = {r.name for r in rates}
    seen: set[str] = set()
    names = {}
    for r in rates:
        name, n = r.name, 1
        while name in seen or (n > 1 and name in taken):
            n += 1
            name = f"{r.name} ({n})"
        seen.add(name)
        names[r.link] = name
    return names


def _rate_table(wb, resources):
    """The rate rows, and the rate-table name each timed resource picks."""
    timed = sorted((r for r in wb.rates if r.kind in _TIMED),
                   key=lambda r: (_TIMED.index(r.kind), r.id))
    library = _library_names(timed)
    rows = [{"trade": _text(library[r.link]), "rate": _amount(r.rate), "kind": r.kind,
             "exchange": {"tag": "RATE", "ref": r.link}} for r in timed]
    library_names = set(library.values())
    picks, local, counts = {}, {}, {}
    for res in resources:
        ref = _library_ref(res, library)
        if ref:
            picks[res.id] = _text(library[ref])
            continue
        key = (res.name, res.unit_cost, res.component_type)
        if key not in local:
            nth = counts[res.name] = counts.get(res.name, 0) + 1
            if nth > 1:
                name = f"{res.name} (local {nth})"
            else:
                name = f"{res.name} (local)" if res.name in library_names else res.name
            local[key] = _text(name)
            rows.append({"trade": local[key], "rate": _amount(res.unit_cost),
                         "kind": res.component_type})
        picks[res.id] = local[key]
    return rows, picks, library


def _time_unit(res, act) -> str:
    """The unit BidSheet.ai prices a timed resource's time in: its own
    ``time_unit``, or when blank the activity's ``production_unit`` (else
    DAYS). The crew row's hours formula reads only HOURS, so a blank unit on
    an HOURS activity is written as HOURS and any other blank stays blank."""
    if res.time_unit:
        return res.time_unit
    return "HOURS" if (act.production_unit or "").upper() == "HOURS" else ""


def _line(res) -> dict:
    line = {"cost_type": _COMPONENT_TYPES.get(res.component_type, res.component_type),
            "name": _text(res.name), "qty": _amount(res.quantity), "uom": res.unit or None,
            "unit_price": _amount(res.unit_cost)}
    first, _, vendor = (p.strip() for p in res.description.partition(" · "))
    if first.casefold() == "quote":
        line["source"] = "quote"
    elif first.casefold() != "plug" and first:
        vendor = res.description.strip()
    if vendor:
        line["vendor"] = _text(vendor)
    line["exchange"] = _exchange(id=res.id, v=res.v)
    return {k: v for k, v in line.items() if v is not None}


def _crew(crew, cid: str) -> dict:
    """A crew copy: the spec's crew shape, plus the copy's code and $/hr (the
    sheet shows them; nothing reads them back). ``cid`` is its unique id."""
    out = {"id": cid, "description": _text(crew.name)}
    if crew.code:
        out["code"] = _text(crew.code)
    out["rate"] = _amount(crew.hourly_rate)
    out["members"] = [{"trade": _text(m.classification), "count": _amount(m.count),
                       "rate": _amount(m.effective_hourly_rate)}
                      for m in sorted(crew.members, key=lambda m: (m.sort_order or 0, m.id))]
    out["exchange"] = _exchange(id=crew.id, v=crew.v)
    return out


def _crew_ids(crews) -> list[str]:
    """Each crew's config id -- its code, or its name when it has none --
    made unique in payload order: "PIPE", "PIPE (2)" (R13). The copies are
    display only, so two crews sharing a code are nothing to refuse."""
    ids, seen = [], set()
    for crew in crews:
        stem = crew.code or crew.name
        cid, n = stem, 1
        while cid in seen:
            n += 1
            cid = f"{stem} ({n})"
        seen.add(cid)
        ids.append(cid)
    return ids


def _server(est) -> dict:
    """BidSheet.ai's bid figures, for the Checks sheet to set beside the book's
    (values only: nothing reads them back)."""
    primary = next((b for b in est.bid_totals if b.is_primary and b.amount is not None), None)
    out = {"bid": _num(primary.amount)} if primary else {}
    return {**out, "markup_amount": _amount(est.markup_amount),
            "markup_text": f"{(est.markup_amount or Decimal(0)):,.2f}"}


def from_model(payload: dict) -> dict:
    try:
        wb = M.parse(payload)
    except M.PayloadError as exc:
        raise FromModelError(str(exc)) from exc
    est = wb.estimate
    _refuse_unshowable(wb)
    shift_hours = _shift_hours(wb)

    by_activity: dict[int, list] = {}
    for res in sorted(wb.resources, key=lambda r: (r.sort_order, r.id)):
        by_activity.setdefault(res.activity_id, []).append(res)
    ordered = [r for a in wb.activities for r in by_activity.get(a.id, ()) if _is_timed(r)]
    rate_rows, picks, library = _rate_table(wb, ordered)

    taken: set[str] = set()
    items = []
    for item in wb.items:
        sheet = sheet_title(f"{item.item_number} - {item.description.upper()}", taken)
        taken.add(sheet)
        tasks = []
        for n, act in enumerate(wb.roots(item.id), start=1):
            task = {"slot": f"{n:02d}", "cost_code": act.code, "description": _text(act.name)}
            if act.description.strip():
                task["notes"] = [_text(note) for note in act.description.splitlines()]
            task["exchange"] = _exchange(id=act.id, v=act.v)
            crew, lines = [], []
            for res in by_activity.get(act.id, ()):
                if _is_timed(res):
                    crew.append({"trade": picks[res.id], "count": _amount(res.quantity),
                                 "days": _amount(res.time_value),
                                 "exchange": _exchange(id=res.id, v=res.v,
                                                       ref=_library_ref(res, library),
                                                       time_unit=_time_unit(res, act))})
                else:
                    lines.append(_line(res))
            if crew:
                task["crew"] = crew
            if lines:
                task["lines"] = lines
            tasks.append(task)
        items.append({"recipe": "lump_sum", "sheet": sheet, "item_no": item.item_number,
                      "description": _text(item.description), "qty": _amount(item.quantity),
                      "uom": item.unit, "exchange": _exchange(id=item.id, v=item.v),
                      "server_cost": _amount(sum((a.cost for a in wb.roots(item.id)),
                                                 Decimal(0))),
                      "labor": tasks})

    config = {"project": _text(est.project_title or est.name), "shift_hours": shift_hours,
              "markup": _markup(est), "rate_table": rate_rows}
    if wb.crews:
        config["crews"] = [_crew(c, cid) for c, cid in zip(wb.crews, _crew_ids(wb.crews))]
        config["crew_copies"] = True
    config["_server"] = _server(est)
    config["items"] = items
    return config
