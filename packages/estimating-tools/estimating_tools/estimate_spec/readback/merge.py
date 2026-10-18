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

from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher

from estimating_tools.estimate_spec.build import coerce_cell_value
from estimating_tools.estimate_spec.readback import layout as L
from estimating_tools.estimate_spec.readback.values import (
    _ISO_DATE, NO_BASELINE, as_text, blank, fmt, read_number, same_number, same_text)


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

def merge_item(item: dict, sheet, f: Findings, *, rate_names, trades, baseline=None) -> None:
    """Merge one item sheet into `item` (in place).

    `baseline`, when given, is the SAME item sheet read from a fresh build of
    the unedited spec -- the only way a formula field whose spec value is a
    placeholder (``={ref:...}``) can tell "unchanged" from "a different
    formula was typed over it"."""
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
    _merge_tasks(item, sheet, where, f, rate_names=rate_names, trades=trades, baseline=baseline)


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
_CY_CF_PAIRS = (("footing_cy", "footing_cf"), ("wall_cy", "wall_cf"), ("deck_cy", "deck_cf"))


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
                 baseline=None) -> None:
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
                old, r, tw, sheet.sheet, f, rate_names, trades, baseline=baseline_row),
            describe=lambda e: f"crew {e.get('trade')} × {fmt(e.get('count', 1))}, "
                               f"{fmt(e.get('days'))} days",
            where=tw, f=f, reorder="crew",
            baseline_list=(baseline_task.crew if baseline_task is not None else None)))
        lines = _merge_list(
            entry.get("lines") or [], task.lines,
            key_of_old=lambda o: as_text(o.get("name")),
            key_of_row=lambda r: as_text(r[L.LINE_NAME]),
            read_row=lambda old, r, baseline_row, tw=tw: _read_line(
                old, r, tw, sheet.sheet, f, baseline=baseline_row),
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


def _read_crew(old, row, where, sheet, f, rate_names, trades, *, baseline=None) -> _Fields:
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
    fields.number("days", row[L.CREW_DAYS],
                  baseline=(baseline[L.CREW_DAYS] if baseline is not None else NO_BASELINE))
    if old is None and fields.ok:
        fields.entry = {k: fields.entry[k] for k in ("trade", "count", "days")}
    return fields


def _read_line(old, row, where, sheet, f, *, baseline=None) -> _Fields:
    fields = _Fields(old, where, row.row, sheet, f)
    fields.choice("cost_type", row[L.LINE_TYPE], L.LINE_TYPES)
    fields.text("name", row[L.LINE_NAME], required=True)
    fields.number("qty", row[L.LINE_QTY],
                  baseline=(baseline[L.LINE_QTY] if baseline is not None else NO_BASELINE))
    fields.text("uom", row[L.LINE_UOM])
    fields.number("unit_price", row[L.LINE_PRICE],
                  baseline=(baseline[L.LINE_PRICE] if baseline is not None else NO_BASELINE))
    if blank(row[L.LINE_SOURCE]):
        # Never a silent plug: a QUOTE line whose Source was cleared would
        # otherwise turn into a plug with nothing in the report.
        fields._problem(f"Source is blank -- choose {' or '.join(L.LINE_SOURCES)}")
    else:
        fields.choice("source", row[L.LINE_SOURCE], L.LINE_SOURCES, default="plug")
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
