"""Merge what the workbook says into a copy of the spec, recording every difference.

Rows are matched to spec entries by name, in order (`align`): an unchanged
row keeps its spec entry exactly -- fields the workbook does not show
(a task's `slot`, a measured line's `footing_cf`, any `x-` key) travel
untouched -- an edited row updates only the fields it shows, a row with no
match is new, and a spec entry with no row was deleted in Excel. Tasks are
matched by the cost code in their header, never by the hidden code tag; when
exactly one code is gone and exactly one new code shows at the same position
in the item, the code was retyped -- a rename that keeps the task (its slot
and hidden fields), not a removal plus a new task.

Everything is edited in place -- the same mapping and sequence objects, keys
set where they stand, rows deleted and inserted one by one -- so a spec loaded
with ruamel.yaml's round-trip loader keeps its comments, key order and layout
when it is written back (`spec_io`).
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher

from estimating_tools.estimate_spec.build import coerce_cell_value
from estimating_tools.estimate_spec.readback import layout as L
from estimating_tools.estimate_spec.readback.values import (
    _ISO_DATE, NO_BASELINE, as_text, blank, fmt, is_number, read_number, same_number, same_text)
from estimating_tools.quotes.files import quote_file_slug
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine


def _match_key(v) -> str:
    """Canonical matching key: run `v` through the SAME text -> cell
    conversion the builder applies, so a cost code, item number or note the
    conversion reshapes (`"31.20"` becomes the cell `31.2`) still matches
    what was read back from the cell -- the same semantics as `same_text`."""
    return "" if blank(v) else as_text(coerce_cell_value(as_text(v)))


@dataclass
class Findings:
    changes: list = field(default_factory=list)      # "where · what"
    needs_rate: dict = field(default_factory=dict)   # resource -> ["item 2 · 02-100", ...]
    overwrites: list = field(default_factory=list)
    quote_edits: list = field(default_factory=list)  # package sheet edits to vendor quote files
    untagged: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    problems: list = field(default_factory=list)     # any one blocks --write

    def absorb(self, noticed) -> None:
        self.overwrites += noticed.overwrites
        self.untagged += noticed.untagged
        self.notices += noticed.notices
        self.problems += noticed.problems


def align(old_keys: list, new_keys: list) -> list:
    """[(old index | None, new index | None)] in sheet order. Equal runs pair
    up; a replaced run of the same length pairs position by position (rows
    retyped in place, e.g. a crew row's resource changed); any other run
    reads as deleted rows followed by new ones."""
    pairs = []
    matcher = SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        same_length = i2 - i1 == j2 - j1
        n = i2 - i1 if tag == "equal" or (tag == "replace" and same_length) else 0
        pairs += [(i1 + k, j1 + k) for k in range(n)]
        pairs += [(i, None) for i in range(i1 + n, i2)]
        pairs += [(None, j) for j in range(j1 + n, j2)]
    return pairs


class _Fields:
    """Merge one row's cells into one spec entry, collecting the differences."""

    def __init__(self, old: dict | None, where: str, row: int, sheet: str, f: Findings):
        self.old, self.where, self.row, self.sheet, self.f = old or {}, where, row, sheet, f
        self.new = old is None          # a new row: no spec value, so no defaults to match
        self.entry = old if old is not None else {}      # edited in place
        self.diffs = []
        self.ok = True

    def _was(self, key, default):
        return None if self.new else self.old.get(key, default)

    def _problem(self, what: str) -> None:
        self.ok = False
        at = f" row {self.row}" if self.row else ""
        self.f.problems.append(f"{self.sheet}{at} ({self.where}): {what}")

    def notice(self, what: str) -> None:
        at = f" row {self.row}" if self.row else ""
        self.f.notices.append(f"{self.sheet}{at} ({self.where}): {what}")

    def text(self, key, cell, *, required=False, default=""):
        old = self._was(key, default)
        if required and blank(cell):
            self._problem(f"{key} is blank")
            return
        if same_text(cell, old):
            return
        new = as_text(cell)
        self.diffs.append(f"{key} {fmt(old)} → {fmt(new)}")
        if blank(new):
            self.entry.pop(key, None)
        else:
            self.entry[key] = new

    def number(self, key, cell, *, default=None, required=True, formula_ok=True,
              baseline=NO_BASELINE):
        old = self._was(key, default)
        if required and blank(cell):
            self._problem(f"{key} is blank")
            return
        if same_number(cell, old, baseline=baseline):
            return
        if blank(cell):
            self.diffs.append(f"{key} {fmt(old)} → (blank)")
            self.entry.pop(key, None)
            return
        new, why = read_number(cell, formula_ok=formula_ok)
        if why:
            self._problem(f"{key} {why}")
            return
        self.diffs.append(f"{key} {fmt(old)} → {fmt(new)}")
        self.entry[key] = new

    def choice(self, key, cell, labels: dict, *, default=None, required=True):
        old = self._was(key, default)
        wanted = {k.lower(): v for k, v in labels.items()}.get(as_text(cell).strip().lower())
        if wanted is None:
            if blank(cell) and not required:
                wanted = default
            else:
                self._problem(f"{key} {fmt(cell)} is not one of {', '.join(labels)}")
                return
        if wanted != old:
            self.diffs.append(f"{key} {fmt(old)} → {fmt(wanted)}")
            self.entry[key] = wanted


def _store_list(owner: dict, key: str, items: list) -> None:
    """Make `owner[key]` hold `items`, editing the sequence already there (and
    so keeping the comments attached to its rows): rows no longer in `items`
    are deleted, a row reordered (the same object, elsewhere in `items`) is
    MOVED rather than duplicated, and a brand new one is inserted where it
    belongs. Kept rows are the very objects already in the sequence."""
    seq = owner.get(key)
    if not isinstance(seq, list):
        owner[key] = items
        return
    keep = {id(x) for x in items}
    for i in range(len(seq) - 1, -1, -1):
        if id(seq[i]) not in keep:
            del seq[i]
    for i, x in enumerate(items):
        if i < len(seq) and seq[i] is x:
            continue
        j = next((k for k in range(i, len(seq)) if seq[k] is x), None)
        seq.insert(i, seq.pop(j) if j is not None else x)
    assert len(seq) == len(items)


def _permutation(old_keys: list, new_keys: list) -> list | None:
    """[(old index, new index)] in sheet order when `new_keys` is `old_keys`
    reordered (the same names, as often each, in another order) -- the n-th
    row showing a name pairs with the spec's n-th entry of that name. Else None."""
    if old_keys == new_keys or sorted(old_keys) != sorted(new_keys):
        return None
    where: dict = {}
    for i, k in enumerate(old_keys):
        where.setdefault(k, []).append(i)
    return [(where[k].pop(0), j) for j, k in enumerate(new_keys)]


def _merge_list(old_list, rows, key_of_old, key_of_row, read_row, describe, where, f,
                baseline_list=None, reorder=None):
    """Merge `rows` into `old_list`; returns the new list of entries (an
    unreadable new row is dropped, an unreadable matched row keeps its entry).

    `baseline_list`, when given, is a fresh-build's own rows for `old_list`,
    aligned with it 1:1 by position (both come from the same unedited spec,
    in the same order) -- `read_row` gets the matching one for a placeholder
    formula field to compare the edited cell against.

    `reorder`, when given, names the rows ("crew"): rows that only changed
    places (moved, or swapped in place) are reported as "<reorder> reordered"
    and written in their new order, not as removed and new rows."""
    old_keys, new_keys = [key_of_old(o) for o in old_list], [key_of_row(r) for r in rows]
    pairs = _permutation(old_keys, new_keys) if reorder else None
    if pairs is not None:
        f.changes.append(f"{where} · {reorder} reordered")
    out = []
    for oi, ni in pairs if pairs is not None else align(old_keys, new_keys):
        if ni is None:
            f.changes.append(f"{where} · − {describe(old_list[oi])} (removed)")
            continue
        old = old_list[oi] if oi is not None else None
        name = key_of_old(old) if old is not None else None    # before the edit renames it
        baseline_row = (baseline_list[oi] if baseline_list is not None and oi is not None
                       and oi < len(baseline_list) else None)
        fields = read_row(old, rows[ni], baseline_row)
        if fields.ok and old is None:
            f.changes.append(f"{where} · + {describe(fields.entry)}")
        elif fields.ok and fields.diffs:
            f.changes.append(f"{where} · {name}: {', '.join(fields.diffs)}")
        out.append(fields.entry if fields.ok else old)
    return [e for e in out if e is not None]


# ------------------------------------------------------------------ rates

def merge_rates(spec: dict, rates, f: Findings) -> None:
    f.absorb(rates.noticed)
    fields = _Fields(spec, "shift hours", None, L.RATES_SHEET, f)
    if not rates.shift_found:
        # Never "blank": the crew formulas still read the hours from that cell.
        f.problems.append(f"{L.RATES_SHEET}: no {L.SHIFT_LABEL!r} row -- its label was changed; "
                          f"restore {L.SHIFT_LABEL!r}")
    else:
        fields.number("shift_hours", rates.shift_hours, default=8, formula_ok=False)
    if fields.ok and fields.diffs:
        spec["shift_hours"] = fields.entry["shift_hours"]
        f.changes.append(f"rates · {fields.diffs[0]}")
    _store_list(spec, "rate_table", _merge_list(
        spec.get("rate_table") or [], rates.rows,
        key_of_old=lambda o: as_text(o.get("trade")),
        key_of_row=lambda r: as_text(r[L.RATE_NAME]).strip(),
        read_row=lambda old, r, baseline: _read_rate(old, r, f),
        describe=_describe_rate, where="rates", f=f))


def _describe_rate(e: dict) -> str:
    kind = e.get("kind", "labor")
    return f"{e.get('trade')} ({kind}, {fmt(e.get('rate'))}/hr)"


def _read_rate(old, row, f: Findings) -> _Fields:
    name = as_text(row[L.RATE_NAME]).strip()
    fields = _Fields(old, f"rate {name or '(no name)'}", row.row, L.RATES_SHEET, f)
    fields.text("trade", name, required=True)
    fields.choice("kind", row[L.RATE_KIND], L.RATE_KINDS, default="labor")
    kind = fields.entry.get("kind", "labor")
    breakdown = not blank(row[L.RATE_BASE])
    if breakdown and kind == "equipment":
        fields._problem("an equipment rate is a flat rate -- clear Base, Burden % and Fringe")
        return fields
    if breakdown:
        if not blank(row[L.RATE_FLAT]):
            fields.notice("flat rate (G) is ignored on a breakdown row")
        before = len(fields.diffs)
        fields.number("base", row[L.RATE_BASE], formula_ok=False)
        fields.number("burden_pct", 0 if blank(row[L.RATE_BURDEN]) else row[L.RATE_BURDEN],
                      formula_ok=False)
        fields.number("fringe", row[L.RATE_FRINGE], required=False, formula_ok=False)
        # Only re-derive (and so only ever report) the rate when a breakdown
        # cell actually changed -- else a spec rate a penny off its own
        # breakdown (historical rounding) looks like a change every time,
        # unedited.
        if fields.ok and len(fields.diffs) > before:
            e = fields.entry
            rate = round(e["base"] * (1 + e["burden_pct"]) + e.get("fringe", 0), 2)
            fields.number("rate", rate, formula_ok=False)
    else:
        for key in ("base", "burden_pct", "fringe"):
            if key in fields.entry:
                fields.diffs.append(f"{key} {fmt(fields.entry.pop(key))} → (blank)")
        fields.number("rate", row[L.RATE_FLAT], formula_ok=False)
    if kind == "equipment":
        fields.choice("includes_operator", row[L.RATE_OPERATOR], L.OPERATOR,
                      default=False, required=False)
    else:
        if as_text(row[L.RATE_OPERATOR]).strip().lower() == "yes":
            fields.notice("includes operator (F) is ignored on a labor rate")
        fields.entry.pop("includes_operator", None)
    if old is None:     # a new row: the spec's usual key order
        e = fields.entry
        fields.entry = {k: e[k] for k in ("trade", "rate", "kind", "base", "burden_pct",
                                          "fringe", "includes_operator") if k in e}
        if fields.entry.get("kind") == "labor":
            del fields.entry["kind"]
    return fields


# ------------------------------------------------------------------ bid date

def merge_bid_date(spec: dict, cell, found: bool, f: Findings) -> None:
    """The Bid Form's bid date (`sheets.read_bid_date`'s `(value, found)`):
    cleared removes the key (never a blank string); a date, or ISO date
    text, sets it; anything else is a problem; a missing label row is a
    notice."""
    if not found:
        f.notices.append(
            f"{L.BID_FORM_SHEET}: no {L.BID_DATE_LABEL!r} row -- the bid date was not read")
    elif blank(cell):
        old = spec.get("bid_date")
        if not blank(old):
            f.changes.append(f"bid date {fmt(old)} → (blank)")
            spec.pop("bid_date", None)
    elif isinstance(cell, (date, datetime)) or (
            isinstance(cell, str) and _ISO_DATE.fullmatch(cell.strip())):
        if not same_text(cell, spec.get("bid_date", "")):
            f.changes.append(f"bid date {fmt(spec.get('bid_date'))} → {fmt(as_text(cell))}")
            spec["bid_date"] = as_text(cell)
    else:
        f.problems.append(
            f"{L.BID_FORM_SHEET}: bid date {cell!r} is not a date -- type it as a date")


# ------------------------------------------------------------------ markup

def _zero_if_blank(cell):
    """A blank markup %, bond or unbalance cell means 0 -- Excel prices it as 0."""
    return 0 if blank(cell) else cell


def merge_markup(spec: dict, markup, f: Findings) -> None:
    f.absorb(markup.noticed)
    spec_markup = spec.setdefault("markup", {})
    for name in L.MARKUP_ROWS:
        row = markup.rows.get(name)
        if row is None:
            f.problems.append(f"{L.MARKUP_SHEET}: the {name!r} row is missing")
            continue
        old_row = spec_markup.get(name) or {}
        for col, cost_type in L.MARKUP_COLS:
            fields = _Fields(old_row, f"markup {name}", row.row, L.MARKUP_SHEET, f)
            fields.number(cost_type, _zero_if_blank(row[col]), default=0, formula_ok=False)
            if fields.ok and fields.diffs:
                spec_markup.setdefault(name, {})[cost_type] = fields.entry[cost_type]
                f.changes.append(f"markup · {name} {fields.diffs[0]}")
    # Excel prices every row in the grid, not just overhead/insurance/profit
    # -- a row the estimator inserts (e.g. "Contingency") would otherwise be
    # silently dropped, with the report saying nothing.
    for name, row in markup.rows.items():
        if name not in L.MARKUP_ROWS:
            shown = row["A"] if not blank(row["A"]) else name
            f.problems.append(
                f"{L.MARKUP_SHEET} row {row.row}: {fmt(shown)!r} is not a fieldbook markup "
                "row -- fold it into Overhead/Profit or delete it")
    fields = _Fields(spec_markup, "bond", None, L.MARKUP_SHEET, f)
    if not markup.bond_found:
        # Not a cleared bond (decision 11's 0): the Bid Form still prices the
        # cell under the renamed label, so reading 0 would change the bid.
        f.problems.append(f"{L.MARKUP_SHEET}: no {L.BOND_LABEL!r} row -- the Bond row's label "
                          f"was changed; restore {L.BOND_LABEL!r}")
    else:
        fields.number("bond_pct", _zero_if_blank(markup.bond), default=0, formula_ok=False)
    if fields.ok and fields.diffs:
        spec_markup["bond_pct"] = fields.entry["bond_pct"]
        f.changes.append(f"markup · {fields.diffs[0]}")
    by_no = {as_text(r["A"]): r for r in markup.unbalance}
    for item in spec.get("items") or []:
        row = by_no.get(_match_key(item.get("item_no")))
        if row is None:
            f.problems.append(f"{L.MARKUP_SHEET}: no unbalance row for item {item.get('item_no')}")
            continue
        fields = _Fields(item, f"item {item.get('item_no')}", row.row, L.MARKUP_SHEET, f)
        fields.number("unbalance", _zero_if_blank(row["C"]), default=0, formula_ok=False)
        if fields.ok and fields.diffs:
            item["unbalance"] = fields.entry["unbalance"]
            f.changes.append(f"item {item.get('item_no')} · {fields.diffs[0]}")


# ------------------------------------------------------------------ items

def merge_item(item: dict, sheet, f: Findings, *, rate_names, trades, baseline=None,
               driven=None) -> None:
    """Merge one item sheet into `item` (in place).

    `baseline`, when given, is the SAME item sheet read from a fresh build of
    the unedited spec -- the only way a formula field whose spec value is a
    placeholder (``={ref:...}``) can tell "unchanged" from "a different
    formula was typed over it".

    `driven` (`driven_cells`) maps `("LINE", line name)` and `("CREW", trade)`
    to the title of the package sheet that drives some of the row's cells: a
    package line's price, Source and vendor, a self-perform task's crew days
    and non-package line qty. Those cells -- the ones whose baseline formula
    reads that sheet -- must still hold that formula; they are never read
    (the spec keeps its plug, source and vendor), and a value typed over one
    is a problem pointing at the package sheet."""
    f.absorb(sheet.noticed)
    where = f"item {item.get('item_no')}"
    if baseline is not None:
        for attr, what in (("description", "item description"), ("uom", "item unit")):
            was, now = getattr(baseline, attr), getattr(sheet, attr)
            if not (blank(was) and blank(now)) and was != now:
                f.notices.append(
                    f"{sheet.sheet} row {sheet.item_row} ({where}): the {what} "
                    f"{fmt(was)!r} → {fmt(now)!r} is not read back -- change it in the "
                    "spec / bid schedule")
    fields = _Fields(item, where, 1, sheet.sheet, f)
    fields.number("qty", sheet.qty, default=1,
                  baseline=(baseline.qty if baseline is not None else NO_BASELINE))
    if fields.ok and fields.diffs:
        item["qty"] = fields.entry["qty"]
        f.changes.append(f"{where} · {fields.diffs[0]}")
    _merge_notes(item, "notes", sheet.notes, where, f)
    if item.get("takeoff") is not None:
        _merge_takeoff(item["takeoff"], sheet, where, f, baseline=baseline)
    _merge_tasks(item, sheet, where, f, rate_names=rate_names, trades=trades, baseline=baseline,
                 driven=driven or {})


def _merge_notes(entry: dict, key: str, rows: list, where: str, f: Findings) -> None:
    old = [_match_key(n) for n in entry.get(key) or []]
    new = [as_text(r["A"]) for r in rows if not blank(r["A"])]
    if new == old:
        return
    for oi, ni in align(old, new):
        if ni is None:
            f.changes.append(f"{where} · − note {old[oi]!r}")
        elif oi is None:
            f.changes.append(f"{where} · + note {new[ni]!r}")
        elif old[oi] != new[ni]:
            f.changes.append(f"{where} · note {old[oi]!r} → {new[ni]!r}")
    if not new:
        entry.pop(key, None)
    elif isinstance(entry.get(key), list):
        entry[key][:] = new             # the same sequence: its style and comments stay
    else:
        entry[key] = new


#: Cubic feet per cubic yard -- a measured line's footing/wall/deck CF is a
#: hidden field the workbook never shows (so it is never read), but it must
#: not go stale when the matching CY field it is derived from changes.
_CF_PER_CY = 27
_CY_CF_PAIRS = (("footing_cy", "footing_cf"), ("wall_cy", "wall_cf"), ("deck_cy", "deck_cf"),
                ("other_cy", "other_cf"))


def _merge_takeoff(takeoff: dict, sheet, where: str, f: Findings, *, baseline=None) -> None:
    kind = takeoff.get("kind")
    if kind not in L.TAKEOFF_FIELDS:
        return
    spec_fields = L.TAKEOFF_FIELDS[kind]

    def read_row(old, r, baseline_row):
        fields = _Fields(old, f"{where} takeoff", r.row, sheet.sheet, f)
        for key, col, numeric in spec_fields:
            if not numeric:
                fields.text(key, r[col], required=key == "label")
            else:
                # Every takeoff quantity is a schema number (never a formula
                # string), and a measured CY derives its hidden CF from it.
                fields.number(key, r[col], required=kind != "measured", formula_ok=False,
                              baseline=(baseline_row[col] if baseline_row is not None
                                       else NO_BASELINE))
        if kind == "measured":
            for cy_key, cf_key in _CY_CF_PAIRS:
                if not any(d.startswith(cy_key + " ") for d in fields.diffs):
                    continue
                if cy_key in fields.entry:
                    fields.entry[cf_key] = round(fields.entry[cy_key] * _CF_PER_CY, 2)
                else:
                    fields.entry.pop(cf_key, None)
        return fields

    list_key = L.TAKEOFF_LIST[kind]
    baseline_rows = baseline.takeoff if baseline is not None else None
    _store_list(takeoff, list_key, _merge_list(
        takeoff.get(list_key) or [], sheet.takeoff,
        key_of_old=lambda o: as_text(o.get("label")),
        key_of_row=lambda r: as_text(r["A"]),
        read_row=read_row,
        describe=lambda e: "takeoff row " + ", ".join(
            f"{k} {fmt(e[k])}" for k, _, _ in spec_fields if k in e),
        where=f"{where} · takeoff", f=f, baseline_list=baseline_rows))


def _merge_tasks(item: dict, sheet, where: str, f: Findings, *, rate_names, trades,
                 baseline=None, driven=None) -> None:
    old_tasks = item.get("labor") or []
    by_code = {_match_key(t.get("cost_code")): t for t in old_tasks}
    baseline_by_code = {as_text(t.code).strip(): t for t in (baseline.tasks if baseline else [])}
    slots = [int(t["slot"]) for t in old_tasks if str(t.get("slot", "")).isdigit()]
    next_slot = max(slots, default=0) + 1
    renamed = _renamed_task(list(by_code), sheet.tasks)       # {new code: old code}
    seen: dict = {}
    out = []
    for task in sheet.tasks:
        code = as_text(task.code).strip()
        if not code:
            f.problems.append(f"{sheet.sheet} row {task.row} ({where}): a task header has no cost code")
            continue
        if code in seen:
            f.problems.append(
                f"{sheet.sheet} rows {seen[code]} and {task.row} ({where}): two task blocks "
                f"show cost code {code} -- give the pasted block its own code, or delete one")
            continue
        seen[code] = task.row
        old = by_code.get(renamed.get(code, code))
        baseline_task = baseline_by_code.get(renamed.get(code, code))
        tw = f"{where} · {code}"
        if code in renamed:
            old["cost_code"] = code
            f.changes.append(f"{where} · task {renamed[code]} renamed to {code}")
        if old is None:
            entry = {"slot": f"{next_slot:02d}", "cost_code": code,
                     "description": as_text(task.description)}
            next_slot += 1
            f.changes.append(f"{where} · + new task {code} {entry['description']} "
                             f"({_count(task.crew, 'crew row')}, {_count(task.lines, 'cost line')}, "
                             f"{_count(task.notes, 'note')})")
        else:
            entry = old
            fields = _Fields(old, tw, task.row, sheet.sheet, f)
            fields.text("description", task.description)
            if fields.diffs:
                entry["description"] = fields.entry.get("description", "")
                f.changes.append(f"{tw} · {fields.diffs[0]}")
        _merge_notes(entry, "notes", task.notes, tw, f)
        _store_list(entry, "crew", _merge_list(
            entry.get("crew") or [], task.crew,
            key_of_old=lambda o: as_text(o.get("trade")),
            key_of_row=lambda r: _resource(as_text(r[L.CREW_TRADE]).strip(), rate_names, trades),
            read_row=lambda old, r, baseline_row, tw=tw: _read_crew(
                old, r, tw, sheet.sheet, f, rate_names, trades, baseline=baseline_row,
                driven=driven),
            describe=lambda e: f"crew {e.get('trade')} × {fmt(e.get('count', 1))}, "
                               f"{fmt(e.get('days'))} days",
            where=tw, f=f, reorder="crew",
            baseline_list=(baseline_task.crew if baseline_task is not None else None)))
        lines = _merge_list(
            entry.get("lines") or [], task.lines,
            key_of_old=lambda o: as_text(o.get("name")),
            key_of_row=lambda r: as_text(r[L.LINE_NAME]),
            read_row=lambda old, r, baseline_row, tw=tw: _read_line(
                old, r, tw, sheet.sheet, f, baseline=baseline_row, driven=driven),
            describe=lambda e: f"line {e.get('name')} {fmt(e.get('qty'))} "
                               f"{e.get('uom', '')} @ {fmt(e.get('unit_price'))} "
                               f"{e.get('cost_type')}".replace("  ", " "),
            where=tw, f=f, reorder="lines",
            baseline_list=(baseline_task.lines if baseline_task is not None else None))
        if lines:
            _store_list(entry, "lines", lines)
        else:
            entry.pop("lines", None)
        out.append(entry)
    # A whole-block reorder, with nothing else edited, must still be
    # reported -- not silently discarded, and not silently applied either.
    new_name = {old: new for new, old in renamed.items()}
    old_order = [new_name.get(c, c) for c in by_code if new_name.get(c, c) in seen]
    new_order = [c for c in seen if c in by_code or c in renamed]
    if old_order != new_order:
        f.changes.append(f"{where} · tasks reordered: {', '.join(_reorder_pairs(old_order, new_order))}")
    for code, old in by_code.items():
        if code not in seen and code not in new_name:
            f.changes.append(f"{where} · − task {code} {old.get('description', '')} (removed)")
    _store_list(item, "labor", out)


def _renamed_task(old_codes: list, tasks: list) -> dict:
    """{new code: old code} when the sheet drops exactly one of the item's
    codes and shows exactly one new code AT THE SAME POSITION -- the estimator
    retyped the code in the header. Anything else is a removal plus a new task."""
    codes = []
    for task in tasks:
        code = as_text(task.code).strip()
        if code and code not in codes:
            codes.append(code)
    gone = [c for c in old_codes if c not in codes]
    new = [c for c in codes if c not in old_codes]
    if len(gone) == 1 and len(new) == 1 and old_codes.index(gone[0]) == codes.index(new[0]):
        return {new[0]: gone[0]}
    return {}


def _reorder_pairs(old_order: list, new_order: list) -> list:
    """Every pair of codes common to both orders whose relative order
    flipped, as "A now before B" -- old_order[A] came before old_order[B],
    new_order has it the other way round."""
    position = {c: i for i, c in enumerate(old_order)}
    return [f"{a} now before {b}" for i, a in enumerate(new_order)
            for b in new_order[i + 1:] if position[a] > position[b]]


def _count(rows, word: str) -> str:
    return f"{len(rows)} {word}{'' if len(rows) == 1 else 's'}"


def _resource(name: str, rate_names, trades) -> str:
    """The rate row's (else the pack's) own spelling of a resource typed in
    another case -- Excel's dropdown and VLOOKUP ignore case, so the workbook
    already priced it as that resource."""
    if name in rate_names or name in trades:
        return name
    for known in list(rate_names) + list(trades):
        if known.lower() == name.lower():
            return known
    return name


def _sheet_ref(title: str):
    """A reference into sheet `title` (`'Sub Hauling'!$F$8`), its row number captured."""
    quoted = re.escape("'" + title.replace("'", "''") + "'")
    bare = re.escape(title)
    return re.compile(rf"((?:{quoted}|(?<![\w']){bare})!\$?[A-Z]{{1,3}}\$?)\d+")


_SP_TYPED = re.compile(r"^=\s*(-?\d+(?:\.\d+)?)\s*\*\s*(.+?)\s*$")


def _self_perform_value(now, base: str, ref):
    """The spec value typed over a self-perform days/qty cell, or None.

    Accepted: a plain number N, or `=N*<the baseline's factor ref>` (the
    built shape with a new N). Anything else (another formula, text) is not."""
    if isinstance(now, (int, float)) and not isinstance(now, bool):
        return now
    if not isinstance(now, str):
        return None
    m = _SP_TYPED.match(now)
    found = ref.search(base)
    if m is None or found is None:
        return None
    if ref.sub(r"\1#", m.group(2)) != ref.sub(r"\1#", found.group(0)):
        return None
    n = float(m.group(1))
    return int(n) if n.is_integer() else n


def _driven_cols(fields: _Fields, old, row, baseline, title, cols: dict) -> set:
    """The columns of `cols` ({column: field word}) that the package sheet
    `title` drives on this row -- those whose baseline formula reads it. Each
    must still hold that formula (rows of the package sheet may have moved,
    so the row numbers into it are not compared); otherwise a problem. A new
    row (no spec entry, no baseline) has no driven cells.

    The exception: a self-perform task's crew days or line qty (`=N*<factor>`)
    takes a plain number or `=<N>*<the same factor ref>` as the new spec value
    N -- the factor is re-applied on rebuild. A package line's price, Source
    and vendor stay refused."""
    if not title or old is None or baseline is None:
        return set()
    ref = _sheet_ref(title)
    out = set()
    for col, what in cols.items():
        base = baseline[col]
        if not (isinstance(base, str) and ref.search(base)):
            continue
        out.add(col)
        now = row[col]
        if isinstance(now, str) and ref.sub(r"\1#", now) == ref.sub(r"\1#", base):
            continue
        if what in ("days", "qty"):
            value = _self_perform_value(now, base, ref)
            if value is not None:
                was = fields._was(what, None)
                if not same_number(value, was):
                    fields.diffs.append(f"{what} {fmt(was)} → {fmt(value)}")
                    fields.entry[what] = value
                fields.notice(f"{what} {fmt(value)} typed over the self-perform formula -- "
                              f"the self-perform factor ({title}) is re-applied on rebuild")
                continue
            fields._problem(f"{what} is driven by the {title} sheet -- type a number (the new "
                            f"{what}; the self-perform factor is re-applied on rebuild) or "
                            "change the selector there")
            continue
        fields._problem(f"{what} is driven by the {title} sheet -- change the selector or the "
                        "vendor price there")
    return out


def _read_crew(old, row, where, sheet, f, rate_names, trades, *, baseline=None,
               driven=None) -> _Fields:
    typed = as_text(row[L.CREW_TRADE]).strip()
    name = _resource(typed, rate_names, trades)
    fields = _Fields(old, where, row.row, sheet, f)
    if name != typed:
        f.notices.append(f"{sheet} row {row.row} ({where}): resource {typed!r} read as "
                         f"{name!r} (same name, different case)")
    if name and trades and name not in trades:
        fields._problem(f"resource {name!r} is not one of this pack's resources "
                        "(pick one from the dropdown)")
    fields.text("trade", name, required=True)
    fields.number("count", row[L.CREW_COUNT], default=1,
                  baseline=(baseline[L.CREW_COUNT] if baseline is not None else NO_BASELINE))
    skip = _driven_cols(fields, old, row, baseline, (driven or {}).get(("CREW", name)),
                        {L.CREW_DAYS: "days"})
    if L.CREW_DAYS not in skip:
        fields.number("days", row[L.CREW_DAYS],
                      baseline=(baseline[L.CREW_DAYS] if baseline is not None else NO_BASELINE))
    if old is None and fields.ok:
        fields.entry = {k: fields.entry[k] for k in ("trade", "count", "days")}
    return fields


def _read_line(old, row, where, sheet, f, *, baseline=None, driven=None) -> _Fields:
    fields = _Fields(old, where, row.row, sheet, f)
    # Checked before anything is read: a driven Source/vendor cell holds a
    # formula, which the Source choice would refuse.
    skip = _driven_cols(fields, old, row, baseline,
                        (driven or {}).get(("LINE", old.get("name") if old else None)),
                        {L.LINE_QTY: "qty", L.LINE_PRICE: "unit price",
                         L.LINE_SOURCE: "source", L.LINE_VENDOR: "vendor"})
    fields.choice("cost_type", row[L.LINE_TYPE], L.LINE_TYPES)
    fields.text("name", row[L.LINE_NAME], required=True)
    if L.LINE_QTY not in skip:
        fields.number("qty", row[L.LINE_QTY],
                      baseline=(baseline[L.LINE_QTY] if baseline is not None else NO_BASELINE))
    fields.text("uom", row[L.LINE_UOM])
    if L.LINE_PRICE not in skip:
        fields.number("unit_price", row[L.LINE_PRICE],
                      baseline=(baseline[L.LINE_PRICE] if baseline is not None else NO_BASELINE))
    if L.LINE_SOURCE in skip:
        pass
    elif blank(row[L.LINE_SOURCE]):
        # Never a silent plug: a QUOTE line whose Source was cleared would
        # otherwise turn into a plug with nothing in the report.
        fields._problem(f"Source is blank -- choose {' or '.join(L.LINE_SOURCES)}")
    else:
        fields.choice("source", row[L.LINE_SOURCE], L.LINE_SOURCES, default="plug")
    if L.LINE_VENDOR not in skip:
        fields.text("vendor", row[L.LINE_VENDOR])
    if old is None and fields.ok:
        e = fields.entry
        fields.entry = {k: e[k] for k in ("cost_type", "name", "qty", "uom", "unit_price",
                                          "source", "vendor") if k in e}
        fields.entry.setdefault("source", "plug")
    return fields


def find_needs_rate(spec: dict, f: Findings) -> None:
    """Crew resources with no rate row: applied, and listed for the estimator.

    Matched case-insensitively, consistent with decision 8 -- Excel's own
    VLOOKUP ignores case, so a resource spelled in another case than its
    rate row already has a rate and does not need one."""
    names = {as_text(r.get("trade")).lower() for r in spec.get("rate_table") or []}
    for item in spec.get("items") or []:
        for task in item.get("labor") or []:
            for member in task.get("crew") or []:
                if as_text(member.get("trade")).lower() not in names:
                    f.needs_rate.setdefault(member.get("trade"), []).append(
                        f"item {item.get('item_no')} · {task.get('cost_code')}")


# ------------------------------------------------------------------ work packages

@dataclass
class QuoteWrite:
    """A quote file read-back would (re)write: `file_name` in the spec's
    quotes directory, holding `quote`; `reason` says why, for the report."""
    file_name: str
    quote: CanonicalQuote
    reason: str


_ARR, _CARRY = "ARR", "CARRY"


def _fold(v) -> str:
    return as_text(v).strip().casefold()


def driven_cells(spec: dict, frames: list) -> dict:
    """{item_no: {("LINE", line name) | ("CREW", trade): package sheet title}}
    -- the rows of each item whose cells a package sheet drives (`merge_item`'s
    `driven`): every package line, and every crew row and non-package line of
    a self-perform task the package switches off (`PackageFrame.sp_tasks`)."""
    items = {str(i.get("item_no")): i for i in spec.get("items") or []}
    out: dict = {}
    for fr in frames:
        for ln in fr.lines:
            out.setdefault(ln.item_no, {}).setdefault(("LINE", ln.name), fr.title)
        for n, keys in fr.sp_tasks.items():
            mine = out.setdefault(n, {})
            for block in (items.get(n) or {}).get("labor") or []:
                if f"task[{block.get('cost_code', '')}]" not in keys:
                    continue
                for member in block.get("crew") or []:
                    mine.setdefault(("CREW", member.get("trade")), fr.title)
                for line in block.get("lines") or []:
                    if line.get("package") is None:
                        mine.setdefault(("LINE", line.get("name")), fr.title)
    return out


def _price(cell):
    """A vendor price cell as (number | "incl" | "excl", None), or (None, why).
    Blank is an exclusion -- the sheet levels it at the ARR extension."""
    if blank(cell):
        return "excl", None
    if is_number(cell) and math.isfinite(cell):
        return float(cell), None
    if isinstance(cell, str):
        s = cell.strip()
        if s.lower() in ("incl", "excl"):
            return s.lower(), None
        if not s.startswith("="):
            try:
                value = float(s.replace(",", ""))
                if math.isfinite(value):
                    return value, None
            except ValueError:
                pass
    return None, f"{fmt(cell)!r} is not a price, incl or excl"


def _same_price(a, b) -> bool:
    if is_number(a) and is_number(b):
        return same_number(a, b)
    return a == b


def _pop_key(d: dict, key: str) -> None:
    """Remove `key` from a spec mapping whose keys may be ints (`picks: {2: ...}`)."""
    for k in [k for k in d if str(k) == key]:
        del d[k]


def _price_line(ql: QuoteLine, ln, value) -> QuoteLine:
    """`ql` (in place) pricing package line `ln` at `value` (a number, "incl"
    -- folded into the line itself -- or "excl")."""
    ql.amount = ql.quantity = ql.unit_price = ql.folded_into = None
    if value == "incl":
        ql.is_included, ql.folded_into = True, ln.name
    elif value == "excl":
        ql.is_included = False
    else:
        ql.is_included, ql.unit_price = True, value
    return ql


def _set_line(q: CanonicalQuote, ln, value, *, single: bool) -> None:
    """Price package line `ln` on quote `q` (in place) at `value`: its line
    for the item (by line name; a nameless one when the item has a `single`
    package line), else a new line."""
    hit = next((ql for ql in q.lines if not ql.is_alternate
                and str(ql.item_number) == ln.item_no
                and (ql.line_name == ln.name or (ql.line_name is None and single))), None)
    if hit is None:
        hit = QuoteLine(schedule_name=q.lines[0].schedule_name if q.lines else "",
                        item_number=ln.item_no, line_name=ln.name)
        q.lines.append(hit)
    _price_line(hit, ln, value)


def merge_packages(spec: dict, sheets: list, quotes: list, frames: list, f: Findings, *,
                   file_names: list | None = None, baseline: dict | None = None) -> list:
    """Merge the `Sub <package>` sheets (`sheets.read_package_sheet`) into the
    spec's `work_packages` (in place) and into the vendor quotes; returns the
    `QuoteWrite`s for the quote files that changed or are new.

    `frames` are `build_package_frames(spec, quotes)` of the unedited spec --
    what each sheet showed when it was built. The selector, per-item picks,
    CARRY figures and surcharges go to the spec; a vendor's edited price or
    condition rewrites that vendor's quote (a copy: `quotes` is never
    changed); a vendor typed into a spare column is a new quote file.
    `file_names[i]`, when given, is the file `quotes[i]` was read from (else
    the file name is `quote_file_slug`). `baseline`, when given, maps each
    package sheet's title to the same sheet read from a fresh build: a sheet
    with fewer vendor columns than that was built from fewer quote files than
    there are now, and is not read."""
    names = list(file_names) if file_names is not None else [None] * len(quotes)
    pkgs = spec.get("work_packages") or []
    by_name = {}
    for s in sheets:
        by_name.setdefault(_fold(s.name), s)
    known = {_fold(p.get("name")) for p in pkgs}
    for s in sheets:
        if _fold(s.name) not in known:
            f.problems.append(f"{s.sheet}: package {s.name!r} is not one of the spec's work "
                              "packages -- rebuild the workbook")
    # Every quote file name in use -> its vendor: a typed vendor's new file
    # must never land on one of them.
    taken = {(n or quote_file_slug(q.vendor_name, q.work_package_name)): q.vendor_name
             for q, n in zip(quotes, names)}
    writes = []
    for pkg, frame in zip(pkgs, frames):
        sheet = by_name.get(_fold(pkg.get("name")))
        if sheet is None:
            f.problems.append(f"{frame.title}: the workbook has no such sheet for package "
                              f"{pkg.get('name')} -- rebuild the workbook")
            continue
        f.absorb(sheet.noticed)
        if sheet.noticed.problems:
            continue
        base = (baseline or {}).get(frame.title)
        if base is not None and len(sheet.vendors) < len(base.vendors):
            f.problems.append(
                f"{sheet.sheet}: {pkg.get('name')}'s quote files changed since the workbook was "
                f"built ({len(base.vendors)} vendor columns now, {len(sheet.vendors)} on the "
                "sheet; a vendor typed in may already have a quote file) -- rebuild the "
                "workbook and redo the edits")
            continue
        got = _merge_package(pkg, frame, sheet, quotes, names, f, taken)
        for w in got:
            taken.setdefault(w.file_name, w.quote.vendor_name)
        writes += got
    return writes


def _rows_by_line(frame, sheet, f: Findings):
    """[(PackageLine, PkgRow)] pairing each package line with its sheet row
    (by item and line name), or None (with problems) when they do not pair."""
    pairs, left, ok = [], list(sheet.rows), True
    for ln in frame.lines:
        hit = next((r for r in left if _match_key(r.item_no) == _match_key(ln.item_no)
                    and as_text(r.line_name).strip() == ln.name), None)
        if hit is None:
            f.problems.append(f"{sheet.sheet}: no row for item {ln.item_no} {ln.name!r} -- "
                              "rebuild the workbook")
            ok = False
            continue
        left.remove(hit)
        pairs.append((ln, hit))
    for r in left:
        f.problems.append(
            f"{sheet.sheet} row {r.row}: item {fmt(r.item_no)} {fmt(r.line_name)!r} is not a "
            f"line of the package -- tag the item's line with package: {frame.name} in the spec")
        ok = False
    return pairs if ok else None


def _vendor_quote(quotes: list, package: str, vendor: str):
    """The index in `quotes` of the quote the frame shows for `vendor` (its
    latest `quote_date`; the first of equal dates), or None."""
    best = None
    for i, q in enumerate(quotes):
        if _fold(q.work_package_name) != _fold(package) or _fold(q.vendor_name) != _fold(vendor):
            continue
        if best is None or (q.quote_date or "") > (quotes[best].quote_date or ""):
            best = i
    return best


def _merge_package(pkg: dict, frame, sheet, quotes: list, names: list, f: Findings,
                   taken: dict) -> list:
    title, pname = sheet.sheet, pkg.get("name")
    where = f"packages · {pname}"
    quoted = [v for v in frame.vendors if not v.is_spare]
    on_sheet = {_fold(v.name): v for v in sheet.vendors if v.name}
    missing = [v.name for v in quoted if _fold(v.name) not in on_sheet]
    for name in missing:
        f.problems.append(f"{title}: the {name} column is missing or its header was retyped -- "
                          f"restore the header {name!r}")
    pairs = _rows_by_line(frame, sheet, f)
    if missing or pairs is None:
        return []
    count = {}
    for ln in frame.lines:
        count[ln.item_no] = count.get(ln.item_no, 0) + 1
    today = date.today().isoformat()
    ok = True
    # The conditions-grid rows the build added for quoted alternates
    # ("Alternate: <line>"): shown from the quote files, never read back.
    alt_rows = {_fold(a) for v in frame.vendors for a in v.alternates}

    # Vendors typed into spare columns: new quote files.
    new_quotes = []
    quoted_names = {_fold(v.name) for v in quoted}
    for col in sheet.vendors:
        if not col.name:
            if (any(not blank(row.cells.get(col.col)) for _, row in pairs)
                    or any(key == col.col and not blank(cell)
                           for (_, key), cell in sheet.conditions.items())):
                f.problems.append(f"{title}: column {col.col} has prices but no vendor name in its "
                                  f"header -- type the vendor's name in row {sheet.header_row}")
                ok = False
            continue
        if _fold(col.name) in quoted_names:
            continue
        if not blank(col.quote_ref):
            # Only a built quoted column has a quote ref: its file is gone.
            f.problems.append(f"{title}: vendor {col.name!r} has a quote ref but no quote file -- "
                              "a quote file was removed since the build; rebuild the workbook (or, for a "
                              "vendor you just typed in, clear its Quote ref cell)")
            ok = False
            continue
        if _fold(col.name) in (_fold(_ARR), _fold(_CARRY)):
            f.problems.append(f"{title}: a vendor may not be named {col.name!r} (column {col.col})")
            ok = False
            continue
        if _vendor_quote(quotes, pname, col.name) is not None:
            f.problems.append(f"{title}: {col.name} (column {col.col}) already has a quote file; "
                              "edit its column -- rebuild the workbook to see it")
            ok = False
            continue
        lines, priced = [], False
        for ln, row in pairs:
            value, why = _price(row.cells.get(col.name))
            if why:
                f.problems.append(f"{title}!{col.col}{row.row} ({col.name}, item {ln.item_no} "
                                  f"{ln.name}): {why}")
                ok = False
                continue
            lines.append(_price_line(
                QuoteLine(schedule_name="", item_number=ln.item_no, line_name=ln.name), ln, value))
            priced = priced or value != "excl"
        if not priced:
            f.notices.append(f"{title}: vendor {col.name} (column {col.col}) has no prices typed "
                             "under it -- no quote file written")
            continue
        conditions = {text: as_text(cell).strip() for (text, key), cell in sheet.conditions.items()
                      if key == col.name and not blank(cell) and _fold(text) not in alt_rows}
        if not blank(col.surcharge) and (not is_number(col.surcharge)
                                        or not math.isfinite(col.surcharge)):
            f.problems.append(f"{title}: surcharge {fmt(col.surcharge)!r} under {col.name} "
                              "is not a finite number")
            ok = False
            continue
        surcharge = col.surcharge if col.surcharge else None
        fname = quote_file_slug(col.name, pname)
        if fname in taken:
            f.problems.append(f"{title}: typed vendor {col.name!r} would write {fname}, which "
                              f"already belongs to {taken[fname]!r} -- rename the vendor")
            ok = False
            continue
        taken[fname] = col.name
        new_quotes.append(CanonicalQuote(
            vendor_name=col.name, work_package_name=pname, quote_date=today,
            notes=f"entered in workbook on {today}", lines=lines, conditions=conditions,
            surcharge=surcharge))
    vendors = [v.name for v in quoted] + [q.vendor_name for q in new_quotes]

    def resolve(text):
        t = _fold(text)
        for fixed in (_ARR, _CARRY):
            if t == _fold(fixed):
                return fixed
        return next((v for v in vendors if _fold(v) == t), None)

    nobody = f"is not ARR, CARRY or a quoted vendor (vendors: {', '.join(vendors) or 'none'})"

    changes = []
    # The selector.
    if blank(sheet.selector):
        f.problems.append(f"{title}: the selector is blank -- choose ARR, CARRY or a vendor")
        ok = False
    else:
        sel = resolve(sheet.selector)
        if sel is None:
            f.problems.append(f"{title}: selector {as_text(sheet.selector).strip()!r} {nobody}")
            ok = False
        elif sel != frame.selected:
            changes.append(f"{where} · selected {frame.selected} → {sel}")
            pkg["selected"] = sel
    # Per-item picks: column H, the same on each of the item's lines.
    picks = {}
    seen: dict = {}              # item_no -> [(row, resolved pick or None for blank)]
    for ln, row in pairs:
        if blank(row.pick):
            seen.setdefault(ln.item_no, []).append((row.row, None))
            continue
        typed = as_text(row.pick).strip()
        got = resolve(typed)
        if got is None:
            f.problems.append(f"{title} row {row.row}: pick {typed!r} for item {ln.item_no} "
                              f"{nobody}")
            ok = False
            continue
        seen.setdefault(ln.item_no, []).append((row.row, got))
        picks.setdefault(ln.item_no, got)
    for n, got in seen.items():
        # A pick is per item: every line of the item the same (blank counts
        # as a value -- a blank line would follow the selector instead).
        if len({p for _, p in got}) > 1:
            listed = ", ".join(f"row {r} {p or '(blank)'}" for r, p in got)
            f.problems.append(f"{title}: item {n}'s lines carry different picks ({listed}) -- set "
                              "the same pick on every line of the item or clear them")
            ok = False
    for n in frame.items:
        was, now = frame.picks.get(n), picks.get(n)
        if was == now:
            continue
        spec_picks = pkg.setdefault("picks", {})
        _pop_key(spec_picks, n)
        if now is not None:
            spec_picks[n] = now
        if not spec_picks:
            pkg.pop("picks", None)
        changes.append(f"{where} · pick item {n} " + (f"{was} " if was else "") +
                       f"→ {now or '(none)'}")
    # CARRY figures, per package line ($/unit).
    for ln, row in pairs:
        key = ln.item_no if count[ln.item_no] == 1 else f"{ln.item_no}/{ln.name}"
        if blank(row.carry):
            now = None
        else:
            now, why = read_number(row.carry, formula_ok=False)
            if why is None and not math.isfinite(now):
                why = "is not a finite number"
            if why:
                f.problems.append(f"{title} row {row.row} (item {ln.item_no} {ln.name}): CARRY "
                                  f"{why}")
                ok = False
                continue
        was = frame.carry_for(ln)
        if (was is None and now is None) or (was is not None and now is not None
                                             and same_number(now, was)):
            continue
        carry = pkg.setdefault("carry", {})
        _pop_key(carry, ln.item_no)
        _pop_key(carry, f"{ln.item_no}/{ln.name}")
        if now is not None:
            carry[key] = now
        if not carry:
            pkg.pop("carry", None)
        changes.append(f"{where} · carry {key} " + (f"{fmt(was)} " if was is not None else "") +
                       f"→ {fmt(now)}")
    # Surcharges: the spec's override of what the quote says.
    for v in quoted:
        cell = on_sheet[_fold(v.name)].surcharge
        now = 0 if blank(cell) else cell
        if not is_number(now) or not math.isfinite(now):
            f.problems.append(f"{title}: surcharge {fmt(cell)!r} under {v.name} is not a number")
            ok = False
            continue
        if same_number(now, v.surcharge):
            continue
        qi = _vendor_quote(quotes, pname, v.name)
        own = (quotes[qi].surcharge or 0) if qi is not None else 0
        spec_sur = pkg.setdefault("surcharge", {})
        for k in [k for k in spec_sur if _fold(k) == _fold(v.name)]:
            del spec_sur[k]
        if not same_number(now, own):
            spec_sur[v.name] = now
        if not spec_sur:
            pkg.pop("surcharge", None)
        changes.append(f"{where} · surcharge {v.name} {fmt(v.surcharge)} → {fmt(now)}")

    # Existing vendors' prices and conditions: their quote files. Recorded
    # only once the whole package reads cleanly.
    edited: dict = {}            # quote index -> its edited copy
    frozen: set = set()          # lump sums now priced line by line
    edits, notes = [], []
    for v in quoted:
        col = on_sheet[_fold(v.name)]
        qi = _vendor_quote(quotes, pname, v.name)
        if qi is None:
            continue
        fname = names[qi] or quote_file_slug(quotes[qi].vendor_name, pname)

        def copy_of(*, price: bool, qi=qi, v=v, fname=fname):
            q = edited.setdefault(qi, copy.deepcopy(quotes[qi]))
            if price and v.lump_sum and not q.lines and qi not in frozen:
                # A price typed over a prorated cell: the lump sum is priced
                # line by line from now on, every other line at the prorated
                # price the sheet showed. A condition edit alone leaves it be.
                frozen.add(qi)
                for ln in frame.lines:
                    if ln.key in v.cells:
                        _set_line(q, ln, v.cells[ln.key], single=count[ln.item_no] == 1)
                notes.append(f"{title}: {v.name}'s lump sum is now priced line by line "
                             f"in {fname} (its amount {fmt(q.amount)} is kept)")
            return q

        for ln, row in pairs:
            now, why = _price(row.cells.get(col.name))
            if why:
                f.problems.append(f"{title}!{col.col}{row.row} ({v.name}, item {ln.item_no} "
                                  f"{ln.name}): {why}")
                ok = False
                continue
            was = v.cells.get(ln.key, "excl")
            if _same_price(now, was):
                continue
            _set_line(copy_of(price=True), ln, now, single=count[ln.item_no] == 1)
            edits.append(f"{title}!{col.col}{row.row} ({v.name}, item {ln.item_no} "
                         f"{ln.name}): {fmt(was)} → {fmt(now)} written to {fname}")
        typed = {_fold(text): cell for (text, key), cell in sheet.conditions.items()
                 if key == col.name}
        for text in frame.conditions:
            if _fold(text) not in typed:
                continue
            now = as_text(typed[_fold(text)]).strip()
            was = v.conditions.get(_fold(text), "")
            if now == as_text(was).strip():
                continue
            if _fold(text) in alt_rows:
                notes.append(f"{title} ({v.name}, {text!r}): an alternate row shows the quote "
                             "file's alternate line -- edit the quote file to change it")
                continue
            q = copy_of(price=False)
            for k in [k for k in q.conditions if _fold(k) == _fold(text)]:
                del q.conditions[k]
            if now:
                q.conditions[text] = now
            edits.append(f"{title} ({v.name}, condition {text!r}): {fmt(was)} → "
                         f"{fmt(now)} written to {fname}")
    if not ok:
        return []
    f.changes += changes
    f.quote_edits += edits
    f.notices += notes
    writes = [QuoteWrite(names[qi] or quote_file_slug(q.vendor_name, pname), q,
                         f"edited in {title}") for qi, q in sorted(edited.items())]
    for q in new_quotes:
        fname = quote_file_slug(q.vendor_name, pname)
        f.changes.append(f"{where} · new quote {q.vendor_name} → {fname}")
        writes.append(QuoteWrite(fname, q, f"typed into {title}"))
    return writes
