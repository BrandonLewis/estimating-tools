"""What a refresh would do to a book (engine spec, "Refresh", steps 1-3),
worked out row by row without writing anything.

Three versions of every row meet here: the baseline (the read model the book
was built or last patched from, ``book.model``), the fresh read model
(BidSheet.ai now), and the book (through the reader: ``changes`` places
every baseline row in the book, ``change_set`` says which rows the
estimator touched). Per row:

- changed only in BidSheet.ai: its bound inputs, export values, rate link
  (the ``ref`` tag, ``contract.REF_ATTR``) and ``v`` tag are written;
- added in BidSheet.ai (a step, resource or crew member): inserted from its
  kind's prototype at the end of its owner's block (``Insert``);
- deleted in BidSheet.ai and untouched in the book: its row is removed;
- changed on both sides: a ``Collision`` naming the sheet, row and field
  with the server's, the book's and the baseline's values -- unless the
  book already shows the server's values (convergent: nothing to write, and
  the book's field updates disappear with the new baseline; a move or crew
  change the row also carries stays, so the row is not convergent). An
  estimate input the book shows as BidSheet.ai now has it drops out of the
  book's ``estimate.update`` field by field (``Merge.dropped``). A row
  deleted on both sides is convergent; deleted on one side and edited or
  copied on the other is a collision, and so is any server change to a row
  the book copied (the copy would no longer match its source);
- a change the book cannot take in place (rows of kinds the book never
  adds or deletes, a moved activity, a changed crew, bid totals...): a
  ``structural`` line saying what changed and what to do.

``applied`` is the patch's use (the plan of a committed apply of
``change_set``): the rows the apply touched and made are the apply's --
neither collisions nor additions -- so only other users' changes remain.

Comparisons are the reader's (``fields.same``: numbers to 15 significant
digits, text trimmed). Only kinds whose sheet the declaration declares are
compared: ``Scan.sheet_of`` is None for an absent sheet and that kind is
skipped."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from estimating_tools.exchange import contract
from estimating_tools.exchange.patch.prototypes import prototype_rows, spelled
from estimating_tools.exchange.reader import fields as F
from estimating_tools.exchange.reader.blocks import Blocks
from estimating_tools.exchange.reader.rates import rate_rows
from estimating_tools.exchange.reader.report import ARROW, fmt
from estimating_tools.exchange.reader.scan import is_blank, norm_id
from estimating_tools.exchange.types import Collision

__all__ = ["Insert", "Merge", "Written", "expected", "op_key", "plan", "signature"]

REBUILD_HINT = "apply this book's edits, then rebuild it from BidSheet.ai"

#: The ops that only set fields on a row: a row both sides made equal loses
#: them with the new baseline. Every other op on the row (a move, a crew
#: change, a roster) still goes out.
UPDATES = frozenset(("estimate.update", "item.update", "element.set_quantity",
                     "activity.update", "step.update", "resource.update"))


@dataclass(frozen=True)
class Written:
    """One change a refresh takes from BidSheet.ai. ``row`` is the book's
    row as read (None for a row the refresh adds); ``gone``, a row it
    removes. ``render`` numbers the row as the book stands after the
    refresh's row ops (``rowops.RowMap``)."""
    tab: str
    row: object
    text: str
    gone: bool = False

    def render(self, rowmap=None) -> str:
        if self.row is None:
            return f"{self.tab}: {self.text}"
        if self.gone:
            return f"{self.tab}: {self.text} (row {self.row} before the refresh)"
        row = rowmap.row(self.tab, self.row) if rowmap is not None else self.row
        return f"{self.tab} row {row}: {self.text}"

    def __str__(self) -> str:
        return self.render()


def _change(label, name, before, after) -> str:
    return f"{label} {name} {fmt(before)} {ARROW} {fmt(after)} (BidSheet.ai)"


@dataclass
class Insert:
    """Rows of ``kind`` to insert from its prototype above row ``before`` (the
    close marker of ``owner``'s block) on sheet ``key``, in order."""
    key: str
    before: int
    kind: str
    owner: object
    rows: list = field(default_factory=list)


@dataclass
class Merge:
    """The refresh's decision. ``cells``: ``{sheet key: {(row, letter): value}}``
    on existing rows, in the book's current coordinates; ``deletes``:
    ``(sheet key, row)``; ``written``: one ``Written`` per change taken;
    ``dropped``: per index of the book's op, what the new baseline already
    holds of it (None: the whole op; else the field names)."""
    cells: dict = field(default_factory=dict)
    inserts: list = field(default_factory=list)
    deletes: list = field(default_factory=list)
    collisions: list = field(default_factory=list)
    structural: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    written: list = field(default_factory=list)
    convergent: set = field(default_factory=set)
    dropped: dict = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.collisions and not self.structural

    @property
    def empty(self) -> bool:
        return not (self.cells or self.inserts or self.deletes)

    def put(self, key, row, letter, value):
        self.cells.setdefault(key, {})[(row, letter)] = value


def op_key(op):
    """``(row kind, identity)`` of the baseline row an op names, or None for a
    create (``new:`` ref) or an op that names no row."""
    ref = op.get("ref")
    if isinstance(ref, str) and ref.startswith("new:"):
        return None
    kind = contract.OP_ROWS.get(op["op"].split(".", 1)[0])
    if kind is None or ref is None:
        return None
    if kind == "ELEMENT_QTY":
        return kind, (int(ref), (op.get("fields") or {}).get("key"))
    return kind, int(ref)


def signature(op) -> tuple:
    """An op as a refresh must leave it: name, ref and fields (``v`` excluded:
    the new baseline gives every op its new ``v``)."""
    return (op["op"], str(op.get("ref")),
            json.dumps(op.get("fields") or {}, sort_keys=True, default=str))


def expected(change_set, merge) -> list:
    """The ``signature``s of the ops the refreshed book should send, sorted:
    the book's ops less what the new baseline already holds
    (``merge.dropped``: a whole op, or the fields of one; an update left
    with no field is gone)."""
    out = []
    for index, op in enumerate(change_set.ops):
        drop = merge.dropped.get(index, ())
        if drop is None:
            continue
        if drop:
            fields = {k: v for k, v in (op.get("fields") or {}).items() if k not in drop}
            if not fields and op["op"] in UPDATES:
                continue
            op = dict(op, fields=fields)
        out.append(signature(op))
    return sorted(out)


def _dec(value):
    return None if value is None or value == "" else Decimal(str(value))


def cell_value(value, inp=None):
    """A read-model value as a cell holds it (``spelled``); blank text is an
    empty cell."""
    out = spelled(value, inp)
    return None if isinstance(out, str) and not out.strip() else out


def _visible(kind, old, new) -> list:
    """The contract's writable fields of ``kind`` that differ between two
    versions of a row (whatever the book shows of them)."""
    out = []
    for name, spec in contract.FIELDS.get(kind, {}).items():
        attr = spec.attr or name
        if not hasattr(old, attr):
            continue
        if not F.same(F.Input("", name, spec.reader), getattr(new, attr), getattr(old, attr)):
            out.append(name)
    return out


def _text(value) -> str:
    return "" if is_blank(value) else str(value).strip()


def _same_figure(a, b) -> bool:
    """Two as-of-export figures alike: numbers to 15 significant digits,
    anything else as trimmed text."""
    try:
        return F.number_equal(_dec(a), _dec(b))
    except (ArithmeticError, ValueError):
        return _text(a) == _text(b)


class _Plan:
    def __init__(self, book, scanned, changes, change_set, fresh, applied):
        self.book, self.scanned, self.changes = book, scanned, changes
        self.base, self.fresh, self.applied = book.model, fresh, applied
        self.m = Merge()
        self.touched, self.ops = {}, {}
        for index, op in enumerate(change_set.ops):
            key = op_key(op)
            if key is not None:
                self.touched[key] = op["op"]
                self.ops.setdefault(key, []).append((index, op))
        self.created = set(applied.created.values()) if applied is not None else set()
        #: Library crews the apply copied into the estimate, old id -> copy id:
        #: their activities follow the copy, which the patch re-ids in place.
        self.crew_copies = {}
        for k, made in (applied.created.items() if applied is not None else ()):
            kind, sep, old = str(k).partition(":")
            if kind == "crew" and sep and old.isdigit():
                self.crew_copies[int(old)] = made[1]
        self.copied = {("RESOURCE", n.source.id) for n in changes.new_resources
                       if n.source is not None}
        self.copied |= {("STEP", n.source.id) for n in changes.new_steps if n.source is not None}
        self.copied |= {("ACTIVITY", n.source.id) for n in changes.new_activities
                        if n.source is not None}

    # -- helpers ---------------------------------------------------------

    def structural(self, text):
        self.m.structural.append(f"{text} -- {REBUILD_HINT}")

    def by_apply(self, kind, ident) -> bool:
        """The patch's use: this row was the apply's."""
        return self.applied is not None and (kind, ident) in self.touched

    def tab_of(self, kind):
        """The tab a kind's rows sit on (its owner block's sheet), or None."""
        owner = "CREW" if kind in ("CREW", "MEMBER") else "ACTIVITY"
        key = self.scanned.sheet_of(owner)
        return self.book.tab(key) if key is not None else None

    def deleted_in_book(self, kind, ident) -> bool:
        return any(op["op"].endswith(".delete") for _i, op in self.ops.get((kind, ident), ()))

    def deleted_with(self, activity_id) -> bool:
        """The book deletes this activity or one it sits under: a delete
        carries the subtree, so the rows under it have no op of their own."""
        seen, a = set(), self.base.activity(activity_id)
        while a is not None and a.id not in seen:
            if self.deleted_in_book("ACTIVITY", a.id):
                return True
            seen.add(a.id)
            a = self.base.activity(a.parent_id) if a.parent_id is not None else None
        return False

    def edited_under_delete(self, kind, label, old, new):
        """A row the book deletes along with its activity: a server change to
        it is a collision (the next apply would delete it unseen)."""
        changed = _visible(kind, old, new)
        if changed:
            self.m.collisions.append(Collision(
                self.tab_of(kind), None, f"{label}: changed in BidSheet.ai ({', '.join(changed)}) "
                                         "and deleted in this book with its activity"))

    def converge(self, kind, ident):
        """The book's ops on this row hold what BidSheet.ai now holds: its
        field updates (and a delete of a row BidSheet.ai deleted too) go with
        the new baseline. A row that also moved, or changed crew or roster,
        keeps that op and is not convergent."""
        kept = False
        for index, op in self.ops.get((kind, ident), ()):
            if op["op"] in UPDATES or op["op"].endswith(".delete"):
                self.m.dropped[index] = None
            else:
                kept = True
        if not kept:
            self.m.convergent.add((kind, ident))

    def drop_field(self, kind, ident, name):
        """One field of the book's update of this row is what BidSheet.ai
        now holds: it goes with the new baseline."""
        for index, op in self.ops.get((kind, ident), ()):
            if op["op"] in UPDATES and name in (op.get("fields") or {}):
                drop = self.m.dropped.setdefault(index, set())
                if drop is not None:
                    drop.add(name)

    def close_row(self, key, occ, block):
        """The row of ``block``'s close marker in ``occ``'s block, or None."""
        for line in self.scanned.lines.get(key, ()):
            if line.occ is occ and line.kind == block.close:
                return line.row
        return occ.end_row if block.close == occ.blocks.last.close else None

    def row(self, kind, ident, label, lines, old, new, *, stepped=False):
        """One baseline row present on both sides; ``lines`` are its book
        rows (``(line, kind)``; an item has two, a row the book deleted
        none)."""
        book, m = self.book, self.m
        if self.by_apply(kind, ident):
            return
        op = self.touched.get((kind, ident))
        changed = (getattr(old, "v", None) != getattr(new, "v", None)) if hasattr(old, "v") \
            else True
        # ``v`` decides only whether the row's v tag is rewritten: fields are
        # compared whatever it says.
        if op is not None and op.endswith(".delete"):
            gone = _visible(kind, old, new)
            if gone:
                m.collisions.append(Collision(self.tab_of(kind), None,
                                              f"{label}: changed in BidSheet.ai "
                                              f"({', '.join(gone)}) and deleted in this book"))
            return
        diffs = []
        for line, k in lines:
            for inp in F.inputs_for(book, line.sheet, k, stepped=stepped):
                before, after = getattr(old, inp.base_attr), getattr(new, inp.base_attr)
                if not F.same(inp, after, before):
                    diffs.append((line, k, inp, before, after))
        exports = []
        for line, k in lines:
            for letter, attr, _label in F.export_values(book, line.sheet, k):
                before, after = getattr(old, attr), getattr(new, attr)
                if not F.number_equal(_dec(after), _dec(before)):
                    exports.append((line, letter, attr, before, after))
        links = []
        attr = contract.REF_ATTR.get(kind)
        if attr is not None:
            for line, _k in lines:
                letter = book.decl.sheets[line.sheet].tag("ref")
                if letter and norm_id(getattr(old, attr)) != norm_id(getattr(new, attr)):
                    links.append((line, letter, getattr(new, attr)))
        # The patch's use: a copy the apply made is already BidSheet.ai's, so a
        # change to its source (the apply's own restamp, or another user's)
        # cannot make it stale.
        if self.applied is None and (kind, ident) in self.copied and lines and (
                changed or diffs or exports or links or _visible(kind, old, new)):
            # Any change, priced or not (a description, a cost code): the
            # copy's create carries the source as the book shows it.
            line = lines[0][0]
            m.collisions.append(Collision(book.tab(line.sheet), line.row,
                                          f"{label}: changed in BidSheet.ai and copied in this "
                                          "book -- the copy would no longer match its source"))
            return
        if op is not None and diffs:
            mismatched = []
            for line, k in lines:
                read = F.read_line(book, line, k, stepped=stepped)
                for inp in F.inputs_for(book, line.sheet, k, stepped=stepped):
                    mine, theirs = read.values.get(inp.field), getattr(new, inp.base_attr)
                    if not F.same(inp, mine, theirs):
                        mismatched.append((line, inp, getattr(old, inp.base_attr), theirs, mine))
            if mismatched:
                for line, inp, before, theirs, mine in mismatched:
                    heading = F.heading(book, line.sheet, inp.letter)
                    m.collisions.append(Collision(
                        book.tab(line.sheet), line.row,
                        f"{label} {heading}: BidSheet.ai {fmt(theirs)}, this book {fmt(mine)} "
                        f"(built with {fmt(before)})"))
                return
            self.converge(kind, ident)
            diffs = []                     # the book already shows BidSheet.ai's values
        for line, _k, inp, before, after in diffs:
            m.put(line.sheet, line.row, inp.letter, cell_value(after, inp))
            m.written.append(Written(book.tab(line.sheet), line.row,
                                     _change(label, inp.field, before, after)))
        for line, letter, name, before, after in exports:
            m.put(line.sheet, line.row, letter, cell_value(after))
            m.written.append(Written(book.tab(line.sheet), line.row,
                                     _change(label, name, before, after)))
        for line, letter, value in links:
            m.put(line.sheet, line.row, letter, value)
        if changed and getattr(new, "v", None) is not None:
            for line, k in lines:
                tag = book.kinds.get(line.sheet, {}).get("kinds", {}).get(k, {}).get("v")
                if tag:
                    m.put(line.sheet, line.row, tag, new.v)

    def gone(self, kind, ident, label, line):
        """A baseline row BidSheet.ai deleted."""
        m = self.m
        if self.by_apply(kind, ident):
            return
        op = self.touched.get((kind, ident))
        tab = self.book.tab(line.sheet) if line is not None else self.tab_of(kind)
        row = line.row if line is not None else None
        if op is not None and op.endswith(".delete"):
            self.converge(kind, ident)
            return
        if op is not None:
            m.collisions.append(Collision(tab, row, f"{label}: deleted in BidSheet.ai, edited in "
                                                    "this book"))
            return
        if self.applied is None and (kind, ident) in self.copied:
            m.collisions.append(Collision(tab, row, f"{label}: deleted in BidSheet.ai, copied in "
                                                    "this book"))
            return
        if line is None:
            return
        m.deletes.append((line.sheet, line.row))
        m.written.append(Written(tab, row, f"{label} removed (deleted in BidSheet.ai)", gone=True))

    # -- per kind --------------------------------------------------------

    def estimate(self):
        book, m = self.book, self.m
        b, f = self.base.estimate, self.fresh.estimate
        if _totals(b) != _totals(f):
            self.structural("the estimate's bid totals were changed in BidSheet.ai")
        if _sections(b) != _sections(f):
            self.structural("the estimate's sections were added, removed or moved in "
                            "BidSheet.ai")
        # As-of-export figures a formula reads (the Bid Form's indirect
        # cost): no op writes them, so BidSheet.ai's is written whatever the
        # book did.
        for line in self.changes.figures:
            named = book.decl.sheets[line.sheet].named_rows
            before, after = getattr(b, line.name, None), getattr(f, line.name, None)
            if _same_figure(after, before):
                continue
            shown = book.ws(line.sheet)[f"{named.value_column}{line.row}"].value
            if not _same_figure(shown, before):
                m.notes.append(f"{book.tab(line.sheet)} row {line.row}: the {line.name} typed "
                               f"here ({fmt(shown)}) is replaced by BidSheet.ai's {fmt(after)} -- "
                               "it is as of export; change it in BidSheet.ai")
            m.put(line.sheet, line.row, named.value_column, cell_value(after))
            m.written.append(Written(book.tab(line.sheet), line.row,
                                     _change("estimate", line.name, before, after)))
        if self.by_apply("ESTIMATE", b.id):
            return
        op = self.touched.get(("ESTIMATE", b.id))
        inputs = book.estimate_inputs
        lines = {line.name: line for line in self.changes.estimate if line.name in inputs}
        mine = {n: F.read_estimate_input(book, line).values.get(n) for n, line in lines.items()}
        clash = False
        for name, line in lines.items():
            inp, before, after = inputs[name], getattr(b, name), getattr(f, name)
            if F.same(inp, after, before):
                continue          # unchanged in BidSheet.ai
            if F.same(inp, mine[name], after):
                # The book already shows it: the book's update of this field
                # goes with the new baseline, whatever else it changed.
                self.drop_field("ESTIMATE", b.id, name)
                continue
            if op is not None and not F.same(inp, mine[name], before):
                m.collisions.append(Collision(
                    book.tab(line.sheet), line.row,
                    f"estimate {name}: BidSheet.ai {fmt(after)}, this book {fmt(mine[name])} "
                    f"(built with {fmt(before)})"))
                clash = True
                continue
            m.put(line.sheet, line.row, inp.letter, cell_value(after, inp))
            m.written.append(Written(book.tab(line.sheet), line.row,
                                     _change("estimate", name, before, after)))
        if op is not None and not clash and all(
                F.same(inputs[n], mine[n], getattr(f, n)) for n in lines):
            self.converge("ESTIMATE", b.id)
        line = next((x for x in self.changes.estimate if x.kind == "ESTIMATE"), None)
        if line is not None and b.v != f.v:
            tag = book.kinds.get(line.sheet, {}).get("kinds", {}).get("ESTIMATE", {}).get("v")
            if tag:
                m.put(line.sheet, line.row, tag, f.v)

    def items(self):
        base, fresh = self.base, self.fresh
        included = any("ITEM.included" in s.formulas for s in self.book.decl.sheets.values())
        for item in base.items:
            label = f"item {item.item_number}"
            if self.by_apply("ITEM", item.id):
                continue
            new = fresh.item(item.id)
            if new is None:
                self.structural(f"{label} ({item.description}) was deleted in BidSheet.ai")
                continue
            if (item.section_id, item.schedule_id) != (new.section_id, new.schedule_id):
                self.structural(f"{label} moved to another section or schedule in BidSheet.ai")
                continue
            if included and item.scope == "excluded" and new.scope != "excluded":
                self.structural(f"{label} was brought into scope in BidSheet.ai; its row has no "
                                "in-scope formulas")
                continue
            lines = self.changes.items.get(item.id) or {}
            pairs = [(lines[k], kind) for k, kind in (("cost", "ITEM"), ("bid", "ITEM_BID"))
                     if k in lines]
            if pairs:
                self.row("ITEM", item.id, label, pairs, item, new)
        for item in fresh.items:
            if base.item(item.id) is None:
                self.structural(f"item {item.item_number} ({item.description}) was added in "
                                "BidSheet.ai")

    def quantities(self):
        lines = {(e.id, q.key): line for line, e, q in self.changes.quantities}
        old = {(e.id, q.key): q for e in self.base.elements for q in e.quantities}
        new = {(e.id, q.key): q for e in self.fresh.elements for q in e.quantities}
        for key, q in old.items():
            if self.by_apply("ELEMENT_QTY", key):
                continue
            if key not in new:
                self.structural(f"element quantity {q.label} ({key[1]}) was deleted in "
                                "BidSheet.ai")
                continue
            if key in lines:
                self.row("ELEMENT_QTY", key, f"element quantity {q.label}",
                         [(lines[key], "ELEMENT_QTY")], q, new[key])
        for key in sorted(new.keys() - old.keys(), key=str):
            self.structural(f"element quantity {new[key].label} ({key[1]}) was added in "
                            "BidSheet.ai")

    def activities(self):
        occs = {occ.id: occ for occ in self.changes.activities}
        for a in self.base.activities:
            label = f"activity {a.name!r}"
            if self.by_apply("ACTIVITY", a.id):
                continue
            new = self.fresh.activity(a.id)
            if new is None:
                # Deleted on both sides: by its own op, or under a parent the
                # book deletes (one delete carries the subtree).
                if self.deleted_with(a.id):
                    self.converge("ACTIVITY", a.id)
                else:
                    self.structural(f"{label} (activity {a.id}) was deleted in BidSheet.ai")
                continue
            moved = [k for k in contract.PLACEMENT.get("ACTIVITY", ())
                     if getattr(a, k) != getattr(new, k)
                     and not (k == "crew_id" and self.crew_copies.get(a.crew_id) == new.crew_id)]
            if moved:
                self.structural(f"{label}: its {', '.join(moved)} changed in BidSheet.ai")
                continue
            if bool(a.steps) != bool(new.steps):
                what = "gained its first step" if new.steps else "lost its last step"
                self.structural(f"{label} {what} in BidSheet.ai")
                continue
            occ = occs.get(a.id)
            if occ is not None:
                self.row("ACTIVITY", a.id, label, [(occ.line, "ACTIVITY")], a, new,
                         stepped=occ.has_steps_marker)
            elif self.deleted_in_book("ACTIVITY", a.id):
                self.row("ACTIVITY", a.id, label, [], a, new)
            elif a.parent_id is not None and self.deleted_with(a.parent_id):
                self.edited_under_delete("ACTIVITY", label, a, new)
        for a in self.fresh.activities:
            if self.base.activity(a.id) is None and ("activity", a.id) not in self.created:
                self.structural(f"activity {a.name!r} was added in BidSheet.ai")

    def children(self, kind):
        """Steps or resources: changed, deleted and added rows."""
        book, m = self.book, self.m
        key = self.scanned.sheet_of("ACTIVITY")
        if key is None:
            return
        block = Blocks(book.decl.sheets[key]).block_of_row(kind)
        if kind == "STEP":
            old = {st.id: (st, a) for a in self.base.activities for st in a.steps}
            new = {st.id: (st, a) for a in self.fresh.activities for st in a.steps}
            lines = {s.id: line for line, s in self.changes.steps}
            noun = "step"
        else:
            old = {r.id: (r, self.base.activity(r.activity_id)) for r in self.base.resources}
            new = {r.id: (r, self.fresh.activity(r.activity_id)) for r in self.fresh.resources}
            lines = {r.id: line for line, r in self.changes.resources}
            noun = "line"
        occs = {occ.id: occ for occ in self.changes.activities}
        for ident, (obj, owner) in old.items():
            label = f"{noun} {obj.name!r}"
            if owner is None or self.fresh.activity(owner.id) is None:
                continue                       # the owner's own change is reported
            if ident not in new:
                self.gone(kind, ident, label, lines.get(ident))
                continue
            fobj, fowner = new[ident]
            if fowner is None or fowner.id != owner.id:
                if not self.by_apply(kind, ident):
                    self.structural(f"{label} moved to another activity in BidSheet.ai")
                continue
            line = lines.get(ident)
            if line is not None:
                self.row(kind, ident, label, [(line, kind)], obj, fobj)
            elif self.deleted_in_book(kind, ident):
                self.row(kind, ident, label, [], obj, fobj)
            elif self.deleted_with(owner.id):
                self.edited_under_delete(kind, label, obj, fobj)
        added = {}
        for ident, (obj, owner) in sorted(new.items()):
            if ident in old or (kind.lower(), ident) in self.created or owner is None:
                continue
            if self.base.activity(owner.id) is None:
                continue                       # under an added activity: reported there
            label = f"{noun} {obj.name!r} of activity {owner.name!r}"
            if self.deleted_in_book("ACTIVITY", owner.id):
                m.collisions.append(Collision(book.tab(key), None, f"{label}: added in "
                                              "BidSheet.ai to an activity this book deletes"))
                continue
            occ = occs.get(owner.id)
            if occ is None:
                continue
            proto = prototype_rows(book, kind)
            if block is None or proto is None or proto[1] != proto[2]:
                self.structural(f"{label} was added in BidSheet.ai; this book has no one-row "
                                f"{kind.lower()} prototype to insert it from")
                continue
            before = self.close_row(key, occ, block)
            if before is None:
                self.structural(f"{label} was added in BidSheet.ai; its activity's block has "
                                f"no {block.close} marker")
                continue
            added.setdefault(before, Insert(key, before, kind, owner.id)).rows.append(obj)
        for ins in added.values():
            ins.rows.sort(key=lambda o: (o.sort_order, o.id))
            m.inserts.append(ins)
            owner = self.fresh.activity(ins.owner)
            for obj in ins.rows:
                m.written.append(Written(book.tab(key), None,
                                         f"{noun} {obj.name!r} added to activity "
                                         f"{owner.name!r} from BidSheet.ai"))

    def crews(self):
        book, m = self.book, self.m
        key = self.scanned.sheet_of("CREW")
        if key is None:
            return
        block = Blocks(book.decl.sheets[key]).block_of_row("MEMBER")
        edits = {e.base.id: e for e in self.changes.crews}
        copies = {v for k, v in (self.applied.created.items() if self.applied else ())
                  if k.startswith("crew:")}
        for crew in self.base.crews:
            label = f"crew {crew.name}"
            if self.applied is not None and (("CREW", crew.id) in self.touched
                                             or f"crew:{crew.id}" in self.applied.created):
                continue
            new = self.fresh.crew(crew.id)
            if new is None:
                self.structural(f"{label} was deleted in BidSheet.ai, or copied into the "
                                "estimate")
                continue
            if crew.scope != new.scope:
                self.structural(f"{label} changed from a {crew.scope} crew to a {new.scope} "
                                "crew in BidSheet.ai")
                continue
            edit = edits.get(crew.id)
            if edit is None:
                continue
            olds, news = {x.id: x for x in crew.members}, {x.id: x for x in new.members}

            def same(a, b):
                return (a.classification, a.count, a.hourly_rate_override, a.labor_rate_id) == \
                    (b.classification, b.count, b.hourly_rate_override, b.labor_rate_id)

            members_changed = olds.keys() != news.keys() or any(
                not same(olds[i], news[i]) for i in olds)
            roster_touched = ("CREW", crew.id) in self.touched
            if roster_touched and members_changed and self.same_roster(key, edit, new):
                self.row("CREW", crew.id, label, [(edit.line, "CREW")], crew, new)
                continue
            if roster_touched and members_changed:
                m.collisions.append(Collision(
                    book.tab(key), edit.line.row,
                    f"{label}'s members: BidSheet.ai has {_roster(new)}; this book edited them "
                    f"(built with {_roster(crew)})"))
                continue
            self.row("CREW", crew.id, label, [(edit.line, "CREW")], crew, new)
            if roster_touched:
                continue
            lines = {rr.base.id: rr.line for rr in edit.roster if rr.base is not None}
            for mid, mem in olds.items():
                if mid not in news:
                    if mid in lines:
                        m.deletes.append((key, lines[mid].row))
                        m.written.append(Written(book.tab(key), lines[mid].row,
                                                 f"{label} member {mem.classification!r} "
                                                 "removed (gone in BidSheet.ai)", gone=True))
                elif mid in lines:
                    self.row("MEMBER", (crew.id, mid),
                             f"{label} member {mem.classification!r}",
                             [(lines[mid], "MEMBER")], mem, news[mid])
            added = sorted((news[i] for i in news.keys() - olds.keys()),
                           key=lambda x: (x.sort_order, x.id))
            if not added:
                continue
            proto = prototype_rows(book, "MEMBER")
            before = self.close_row(key, edit.line.occ, block) if block is not None else None
            if proto is None or proto[1] != proto[2] or before is None:
                self.structural(f"{label}'s members were replaced in BidSheet.ai; this book "
                                "has no one-row member prototype to insert them from")
                continue
            m.inserts.append(Insert(key, before, "MEMBER", crew.id, added))
            for x in added:
                m.written.append(Written(book.tab(key), None, f"{label} member "
                                         f"{x.classification!r} added from BidSheet.ai"))
        for crew in self.fresh.crews:
            if self.base.crew(crew.id) is None and ("crew", crew.id) not in copies:
                self.structural(f"crew {crew.name} was added in BidSheet.ai")

    def same_roster(self, key, edit, new) -> bool:
        """The book's roster already is BidSheet.ai's (both sides set a count
        alike, or removed the same member): its member rows and the fresh
        members pair up one to one by content -- inputs and rate link, in
        whatever order either side sorts them. Then each row takes its
        member's id, rate link and export values, and the book's roster op
        goes with the new baseline. A typed member row (no prototype cells
        yet) is never alike."""
        book, m = self.book, self.m
        rows = [rr.line for rr in edit.roster]
        members = sorted(new.members, key=lambda x: (x.sort_order, x.id))
        if len(rows) != len(members) or any(line.kind != "MEMBER" for line in rows):
            return False
        sheet = book.decl.sheets[key]
        ref, ws = sheet.tag("ref"), book.ws(key)

        def alike(line, read, mem):
            for inp in F.inputs_for(book, key, "MEMBER"):
                if not F.same(inp, read.values.get(inp.field), getattr(mem, inp.base_attr)):
                    return False
            link = ws[f"{ref}{line.row}"].value if ref else None
            return is_blank(link) or norm_id(link) == norm_id(mem.labor_rate_id)

        pairs, left = [], list(members)
        for line in rows:
            read = F.read_line(book, line, "MEMBER")
            if not read.ok:
                return False
            mem = next((x for x in left if alike(line, read, x)), None)
            if mem is None:
                return False
            left.remove(mem)
            pairs.append((line, mem))
        id_tag = book.kinds[key]["kinds"].get("MEMBER", {}).get("id")
        exports = sheet.export_values.get("MEMBER", {})
        for line, mem in pairs:
            if id_tag:
                m.put(key, line.row, id_tag, mem.id)
            if ref:
                m.put(key, line.row, ref, mem.labor_rate_id)
            for letter, attr in exports.items():
                m.put(key, line.row, letter, cell_value(getattr(mem, attr)))
        for index, op in self.ops.get(("CREW", edit.base.id), ()):
            if op["op"] == "crew.update_members":
                m.dropped[index] = None
        m.convergent.add(("CREW", edit.base.id))
        return True

    def rates(self):
        book, m = self.book, self.m
        key, sheet = next(((k, s) for k, s in book.decl.sheets.items() if s.role == "rates"),
                          (None, None))
        if sheet is None:
            return
        old = {(r.kind, r.id): r for r in self.base.rates if r.kind in sheet.sections}
        new = {(r.kind, r.id): r for r in self.fresh.rates if r.kind in sheet.sections}
        if old.keys() != new.keys():
            self.structural("library rates were added or removed in BidSheet.ai; the "
                            f"{book.tab(key)} sheet holds them as of the build")
            return
        rows = None
        for k, r in old.items():
            n = new[k]
            if (_text(r.name), _text(r.unit)) == (_text(n.name), _text(n.unit)) \
                    and F.number_equal(_dec(n.rate), _dec(r.rate)):
                continue
            rows = rows if rows is not None else rate_rows(book)
            row = rows.get(k)
            if row is None:
                self.structural(f"{k[0]} rate {r.name!r} is not on the {book.tab(key)} sheet")
                continue
            m.put(key, row, sheet.columns_by_key["name"], cell_value(n.name))
            m.put(key, row, sheet.columns_by_key["unit"], cell_value(n.unit))
            m.put(key, row, sheet.columns_by_key["rate"], cell_value(n.rate))
            m.written.append(Written(book.tab(key), row,
                                     _change(f"{k[0]} rate {r.name!r}", "rate", r.rate, n.rate)))


def _totals(estimate) -> list:
    return [(t.name, t.schedule_ids, t.includes_unscheduled, t.is_primary, t.display_order)
            for t in estimate.bid_totals]


def _sections(estimate) -> list:
    return sorted((s.id, s.schedule_id, s.display_order) for s in estimate.sections)


def _roster(crew) -> str:
    members = sorted(crew.members, key=lambda x: (x.sort_order, x.id))
    return ", ".join(f"{x.classification} x{fmt(x.count)}" for x in members) or "no members"


def plan(book, scanned, changes, change_set, fresh, *, applied=None) -> Merge:
    """What a refresh of ``book`` (the reader's opened book; ``scanned``,
    ``changes`` and ``change_set`` its read) to ``fresh`` (the parsed fresh
    read model) would do. ``applied``: the plan of a committed apply of
    ``change_set`` (the patch's use; see the module docstring)."""
    p = _Plan(book, scanned, changes, change_set, fresh, applied)
    p.estimate()
    p.items()
    p.quantities()
    p.activities()
    p.children("STEP")
    p.children("RESOURCE")
    p.crews()
    p.rates()
    return p.m
