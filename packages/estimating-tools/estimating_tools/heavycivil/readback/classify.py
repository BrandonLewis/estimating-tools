"""Decide what each scanned row is: an existing row (maybe edited or moved),
a new row (copied, pasted or typed), or a baseline row that is gone.

- One occurrence of a known id is the existing row.
- Several occurrences (a copied row): the original is the occurrence under
  its baseline parent whose inputs equal the baseline, else the first under
  its baseline parent, else the first in sheet order; every other occurrence
  is a new row. Among equally good activity occurrences, the one that most
  of the activity's baseline children sit under wins (a parent's block
  pasted above itself keeps its children), then sheet order. Rows inside a copied activity's block are new rows too.
  Activities are decided top-down: a child activity is "under its parent"
  when its positional parent (the nearest occurrence above it, in the same
  item, of the activity its Z cell names) is its parent's original, so a
  parent copied with its children keeps its copied children. An original
  child left under a copy of its parent is refused.
- A step or resource found only in copied blocks, and gone from its own
  activity, was cut into the copy.
- A RESOURCE whose id is not in the baseline was pasted from another book;
  any other kind with a foreign id is refused.
- A baseline id missing from the book is a delete, unless its parent's
  delete already takes it.
- Items, element quantities, crews, sections, bid totals and the estimate's
  rows are never added, copied or deleted by read-back.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from estimating_tools.heavycivil import layout
from estimating_tools.heavycivil.columns import BF, CR
from estimating_tools.heavycivil.readback import fields as F
from estimating_tools.heavycivil.readback.scan import is_blank

MANAGED = "this line is posted by a subcontractor allocation -- change it in BidSheet.ai"
FOREIGN = "only resource rows can be pasted in from another workbook"
NO_ADD = "rows of this kind can't be added or copied in the workbook"
NO_DELETE = "rows of this kind can't be deleted from the workbook -- undo the delete"
MOVE_MANAGED = ("this activity carries subcontractor allocation work (an allocation-posted "
                "line or a subcontractor spread), which is tied to its item -- undo the move")
STRUCTURE = ("structure activities are added, deleted and moved in the takeoff, not the "
             "workbook")
UNDER_COPY = ("this activity now sits under a copy of its parent -- copy the parent with "
              "its children, or undo")
LINKED_COPY = ("activity {name!r} is linked to elements/spreads and was copied with one "
               "copy edited (rows {rows}) -- BidSheet.ai can't tell which row keeps the "
               "links; undo the edit, apply the copy, rebuild, then edit")
DETACHED_STRUCTURE = ("this structure activity's parent was deleted, and a structure "
                      "activity can't be re-parented in the workbook -- undo the parent's "
                      "delete")
FIRST_STEP = ("add the activity's first step in BidSheet.ai, then rebuild -- its Shifts "
              "is typed, and a first step would restamp it to a figure the book never showed")
STRAY = ("this row is outside any block a new row can go in -- delete it, or type it "
         "between an activity's START and END markers (a resource), its STEPS and START "
         "markers (a step), or inside a crew's rows (a member)")

_LINK = re.compile(r"^(labor|equipment|material):(\d+)$")
#: Rate-link kind -> the resource field that carries it.
LINK_FIELDS = {"labor": "labor_rate_id", "equipment": "equipment_rate_id",
               "material": "material_cost_id"}


@dataclass
class NewActivity:
    occ: object
    source: object          # the baseline Activity it was copied from
    parent: object          # an activity id, a new: token, or None (a root)


@dataclass
class Move:
    occ: object
    base: object
    #: ``{"item_id": id}`` (to another item, as a root, with its subtree) or
    #: ``{"parent_id": None}`` (a root of its own item: its parent was deleted).
    fields: dict
    depth: int
    detached: bool = False  # its parent was deleted

    @property
    def item_id(self):
        return self.fields.get("item_id", self.occ.item_id)


@dataclass
class NewStep:
    line: object
    occ: object
    source: object = None   # the baseline Step (copy, cut)
    how: str = "typed"      # "copy" | "typed" | "cut"


@dataclass
class NewResource:
    line: object
    occ: object
    how: str                # "copy" | "paste" | "typed" | "cut"
    source: object = None   # the baseline Resource (copy, cut)
    link: dict = field(default_factory=dict)   # rate field -> id (paste)


@dataclass
class RosterRow:
    line: object
    base: object = None     # the baseline Member this row is
    source: object = None   # the baseline Member it was copied from


@dataclass
class CrewEdit:
    line: object
    base: object
    roster: list = field(default_factory=list)
    removed: list = field(default_factory=list)


@dataclass
class Changes:
    estimate: list = field(default_factory=list)      # ESTIMATE / BID_INPUT lines
    items: dict = field(default_factory=dict)         # item id -> {"cost": line, "bid": line}
    quantities: list = field(default_factory=list)    # (line, element, quantity)
    activities: list = field(default_factory=list)    # original occurrences
    new_activities: list = field(default_factory=list)
    moves: list = field(default_factory=list)
    steps: list = field(default_factory=list)         # (line, Step) in place
    new_steps: list = field(default_factory=list)
    resources: list = field(default_factory=list)     # (line, Resource) in place
    new_resources: list = field(default_factory=list)
    crews: list = field(default_factory=list)
    deleted_activities: list = field(default_factory=list)
    deleted_steps: list = field(default_factory=list)      # (Step, Activity)
    deleted_resources: list = field(default_factory=list)
    ignored: list = field(default_factory=list)            # Bid Form rows not read


def _choose(lines, under_parent, equal, rank=None):
    """The original among a copied row's occurrences: the first under its
    parent whose inputs equal the baseline, else the first under its parent,
    else the first. ``rank``: among equally good candidates, the one ranked
    highest wins, then the first in sheet order."""
    def best(found):
        if not found:
            return None
        return found[0] if rank is None else max(found, key=rank)   # max: first of ties
    under = [line for line in lines if under_parent(line)]
    return best([line for line in under if equal(line)]) or best(under) or lines[0]


def _group(lines, key):
    out = {}
    for line in lines:
        out.setdefault(key(line), []).append(line)
    return out


def rate_link(book, line, problems):
    """A pasted resource's rate link from its hidden AE cell, as
    ``{field: id}``; empty when blank."""
    value = book.ws("cost_report")[f"{CR.REF}{line.row}"].value
    if is_blank(value):
        return {}
    match = _LINK.match(str(value).strip())
    if match is None:
        problems.add(book.tab("cost_report"), line.row, CR.REF,
                     f"the hidden rate link {value!r} is unreadable -- clear the cell "
                     "or retype the line")
        return {}
    return {LINK_FIELDS[match.group(1)]: int(match.group(2))}


def _singletons(book, lines, key, expected, label, sheet, problems):
    """Rows that read-back never adds, copies or deletes: one line per
    expected key. Returns ``{key: line}``."""
    tab = book.tab(sheet)
    found = {}
    for line in lines:
        k = key(line)
        if k not in expected or k in found:
            problems.add(tab, line.row, None, NO_ADD)
            continue
        found[k] = line
    for k in expected:
        if k not in found:
            problems.add(tab, None, None, f"{label(k)} is missing -- {NO_DELETE}")
    return found


def _fixed_rows(book, s, ch, problems):
    m = book.model
    cr = [x for x in s.cost_report if x.kind in ("ITEM", "ELEMENT_QTY")]
    items = _singletons(book, [x for x in cr if x.kind == "ITEM"], lambda x: x.id,
                        [i.id for i in m.items], lambda k: f"item {m.item(k).item_number}",
                        "cost_report", problems)
    quantities = {(e.id, q.key): (e, q) for e in m.elements for q in e.quantities}
    qty_lines = _singletons(book, [x for x in cr if x.kind == "ELEMENT_QTY"],
                            lambda x: (x.id, x.key), list(quantities),
                            lambda k: f"element {k[0]} quantity {k[1]}", "cost_report",
                            problems)
    ch.quantities = [(line, *quantities[k]) for k, line in qty_lines.items()]
    for k, line in qty_lines.items():
        F.check_export_values(book, line, quantities[k][1], problems)
    bf = s.bid_form
    bids = _singletons(book, [x for x in bf if x.kind == "ITEM_BID"], lambda x: x.id,
                       [i.id for i in m.items], lambda k: f"item {m.item(k).item_number}",
                       "bid_form", problems)
    for item in m.items:
        ch.items[item.id] = {"cost": items.get(item.id), "bid": bids.get(item.id)}
        if item.id in bids:
            F.check_export_values(book, bids[item.id], item, problems)
    placed = [sec.id for sec in m.estimate.sections
              if any(i.section_id == sec.id and layout.section_of(m, i) is sec
                     for i in m.items)]
    _singletons(book, [x for x in bf if x.kind == "SECTION"], lambda x: x.id, placed,
                lambda k: f"section {k}", "bid_form", problems)
    _singletons(book, [x for x in bf if x.kind == "BID_TOTAL"], lambda x: x.id,
                [t.id for t in m.estimate.bid_totals], lambda k: f"bid total {k}",
                "bid_form", problems)
    named = _singletons(book, [x for x in bf if x.kind in ("ESTIMATE", "BID_INPUT",
                                                             "BID_FIGURE")],
                        lambda x: x.name, list(BF.ROWS),
                        lambda k: f"the {k} row", "bid_form", problems)
    est = named.get("markup_percentage")
    if est is not None and (est.kind != "ESTIMATE" or est.id != m.estimate.id):
        problems.add(book.tab("bid_form"), est.row, None, f"the estimate row is not this "
                     f"book's estimate -- {NO_DELETE}")
    ch.estimate = [named[n] for n in BF.INPUTS if n in named]


def _positions(occs):
    """Each occurrence's positional parent: the nearest occurrence above it,
    under the same item, of the activity its parent cell (Z) names -- the
    parent block it was copied or cut along with, or None."""
    seen, item = {}, object()
    for occ in occs:
        if occ.item_id != item:
            seen, item = {}, occ.item_id
        parent = occ.line.parent
        occ.pos_parent = seen.get(parent) if parent is not None else None
        seen[occ.id] = occ


def _gone_subtree(ix, activity, gone):
    """``activity`` and every descendant its delete cascades to: those
    reached through deleted activities only (a surviving child is moved
    out first)."""
    out, frontier = [activity], [activity.id]
    while frontier:
        kids = [k for f in frontier for k in ix.children.get(f, ()) if k.id in gone]
        out += kids
        frontier = [k.id for k in kids]
    return out


def carries_links(raw) -> bool:
    """The activity holds state a copy cannot keep (``activity.create``
    writes none of it): element links, a measure or pay-as-part-of link,
    a spread, or a measured basis."""
    spread = raw.get("spread") or {}
    return bool(raw.get("element_ids") or raw.get("measured_by")
                or raw.get("paid_as_part_of") or spread.get("items") or spread.get("basis")
                or raw.get("basis_source_measure") or raw.get("basis_source_groups")
                or raw.get("geometry"))


def _linked_copies_differ(book, a, mine, problems, tab):
    """A linked activity copied with the copies' inputs differing: which row
    is the original decides which keeps the links, and the book can't say."""
    if len(mine) < 2 or not carries_links(book.index.raw_activities.get(a.id, {})):
        return
    seen = {tuple(sorted(F.read_line(book, o.line, "ACTIVITY",
                                     stepped=bool(a.steps)).values.items(), key=str))
            for o in mine}
    if len(seen) > 1:
        problems.add(tab, mine[0].line.row, None, LINKED_COPY.format(
            name=a.name, rows=", ".join(str(o.line.row) for o in mine)))


def _activities(book, s, ch, problems):
    m, ix, tab = book.model, book.index, book.tab("cost_report")
    foreign = set()
    for o in s.activities:
        if m.activity(o.id) is None:
            problems.add(tab, o.line.row, None, FOREIGN)
            foreign.add(o)
    occs = [o for o in s.activities if o not in foreign]
    _positions(occs)
    groups = _group(occs, lambda o: o.id)
    child_ids = {pid: {k.id for k in kids} for pid, kids in ix.children.items()}
    # Originals top-down: a child's original must sit under its parent's
    # original, so a parent copied with its children keeps the copied
    # children and the original never gains one.
    orig = {}
    for a in sorted(m.activities, key=lambda a: ix.depth[a.id]):
        mine = groups.get(a.id)
        if not mine:
            continue
        _linked_copies_differ(book, a, mine, problems, tab)
        parent = orig.get(a.parent_id) if a.parent_id is not None else None
        if parent is not None:
            def under(x, p=parent):
                return x.occ.pos_parent is p
        else:
            def under(x, a=a):
                return x.item_id == a.item_id
        kids = [k for k in occs if k.id in child_ids.get(a.id, ())]

        def parent_of(x, kids=kids):
            # How many of its baseline children sit under this occurrence:
            # the original keeps its children wherever a copy was pasted.
            return len({k.id for k in kids if k.pos_parent is x.occ})
        chosen = _choose([o.line for o in mine], under, lambda x, a=a: F.equal_to_base(
            book, x, "ACTIVITY", a, stepped=bool(a.steps)), rank=parent_of).occ
        for o in mine:
            o.original = o is chosen
        orig[a.id] = chosen
        if parent is not None and chosen.pos_parent not in (None, parent):
            problems.add(tab, chosen.line.row, None, UNDER_COPY)
    copies = [o for o in occs if not o.original]
    for n, o in enumerate(copies, 1):
        o.token = f"new:a{n}"
    for occ in copies:
        source = m.activity(occ.id)
        if source.assembly_type == "STRUCTURE":
            problems.add(tab, occ.line.row, None, STRUCTURE)
        z = occ.line.parent
        if occ.pos_parent is not None:
            parent = occ.pos_parent.ref
        elif (z in orig and orig[z].item_id == occ.item_id
              and orig[z].line.row < occ.line.row):
            # Z's original, above it in the same item. Below it (its parent's
            # row above was deleted) the book shows no parent: a root.
            parent = z
        else:
            parent = None
        ch.new_activities.append(NewActivity(occ, source, parent))
    ch.activities = sorted(orig.values(), key=lambda o: o.line.row)
    gone = {a.id for a in m.activities if a.id not in orig}
    for a in m.activities:
        if a.id in gone and (a.parent_id is None or a.parent_id not in gone):
            if any(x.assembly_type == "STRUCTURE" for x in _gone_subtree(ix, a, gone)):
                problems.add(tab, None, None, f"activity {a.id} ({a.name}) was deleted -- "
                             f"{STRUCTURE}")
                continue
            ch.deleted_activities.append(a)
    # Where the server will have each activity before its own move: its
    # parent's final item (a parent's move carries its subtree).
    final = {}
    for a in sorted(m.activities, key=lambda a: ix.depth[a.id]):
        inherited = a.item_id if a.parent_id is None else final[a.parent_id]
        occ = orig.get(a.id)
        if occ is None or occ.item_id is None:
            final[a.id] = inherited
            continue
        final[a.id] = occ.item_id
        detached = a.parent_id is not None and a.parent_id in gone
        if occ.item_id != inherited:
            if m.item(occ.item_id) is None:
                continue   # under an item row from another book: refused (NO_ADD)
            fields = {"item_id": occ.item_id}
        elif detached:
            fields = {"parent_id": None}
        else:
            continue
        if "parent_id" in fields:
            if a.assembly_type == "STRUCTURE":
                problems.add(tab, occ.line.row, None, DETACHED_STRUCTURE)
                continue
        else:
            subtree = [a] + ix.subtree(a.id)
            if any(x.assembly_type == "STRUCTURE" for x in subtree):
                problems.add(tab, occ.line.row, None, STRUCTURE)
                continue
            ids = {x.id for x in subtree}
            if any(r.managed_by and r.activity_id in ids for r in m.resources) or any(
                    x.assembly_type == "SUBCONTRACTOR_SPREADS" for x in subtree):
                problems.add(tab, occ.line.row, None, MOVE_MANAGED)
                continue
        ch.moves.append(Move(occ, a, fields, ix.depth[a.id], detached=detached))
    return orig, foreign, gone


def _typed_in_activity(book, occ, ch, problems):
    tab = book.tab("cost_report")
    for line in occ.typed:
        if line.zone == "steps":
            ch.new_steps.append(NewStep(line, occ))
        elif line.zone == "resources":
            ch.new_resources.append(NewResource(line, occ, "typed"))
        elif not occ.has_steps_marker:
            problems.add(tab, line.row, None, FIRST_STEP)
        else:
            problems.add(tab, line.row, None, STRAY)


def _steps(book, s, ch, foreign, gone, problems):
    m, tab = book.model, book.tab("cost_report")
    by_id = {st.id: (st, a) for a in m.activities for st in a.steps}
    groups, copied = {}, {}
    for occ in s.activities:
        if occ in foreign:
            continue
        for line in occ.steps:
            if line.id not in by_id:
                problems.add(tab, line.row, None, FOREIGN)
            else:
                (groups if occ.original else copied).setdefault(line.id, []).append(line)
    kept = set()
    for sid, lines in groups.items():
        step, act = by_id[sid]
        chosen = _choose(lines, lambda x: x.occ.id == act.id,
                         lambda x: F.equal_to_base(book, x, "STEP", step))
        for line in lines:
            if line is not chosen:
                ch.new_steps.append(NewStep(line, line.occ, step, "copy"))
            elif line.occ.id == act.id:
                ch.steps.append((line, step))
                kept.add(sid)
            else:
                ch.new_steps.append(NewStep(line, line.occ, step, "cut"))
    for sid, lines in copied.items():
        # Only in copied blocks, and gone from its own activity: cut into a copy.
        step, act = by_id[sid]
        cut = sid not in groups and act.id not in gone
        for n, line in enumerate(lines):
            ch.new_steps.append(NewStep(line, line.occ, step, "cut" if cut and not n
                                        else "copy"))
    for sid, (step, act) in by_id.items():
        if sid not in kept and act.id not in gone:
            ch.deleted_steps.append((step, act))


def _resources(book, s, ch, foreign, gone, problems):
    m, tab = book.model, book.tab("cost_report")
    by_id = {r.id: r for r in m.resources}
    groups, copied = {}, {}
    for occ in s.activities:
        if occ in foreign:
            continue
        for line in occ.resources:
            if line.id not in by_id:
                ch.new_resources.append(NewResource(line, occ, "paste",
                                                    link=rate_link(book, line, problems)))
            else:
                (groups if occ.original else copied).setdefault(line.id, []).append(line)
        _typed_in_activity(book, occ, ch, problems)
    kept = set()

    def cut(line, res):
        if res.managed_by:
            problems.add(tab, line.row, None, MANAGED)
            kept.add(res.id)
        else:
            ch.new_resources.append(NewResource(line, line.occ, "cut", res))

    for rid, lines in groups.items():
        res = by_id[rid]
        chosen = _choose(lines, lambda x: x.occ.id == res.activity_id,
                         lambda x: F.equal_to_base(book, x, "RESOURCE", res))
        for line in lines:
            if line is not chosen:
                ch.new_resources.append(NewResource(line, line.occ, "copy", res))
            elif line.occ.id == res.activity_id:
                ch.resources.append((line, res))
                kept.add(rid)
            else:
                cut(line, res)
    for rid, lines in copied.items():
        # Only in copied blocks, and gone from its own activity: cut into a copy.
        res = by_id[rid]
        is_cut = rid not in groups and res.activity_id not in gone
        for n, line in enumerate(lines):
            if is_cut and not n:
                cut(line, res)
            else:
                ch.new_resources.append(NewResource(line, line.occ, "copy", res))
    for res in m.resources:
        if res.id in kept:
            continue
        if res.managed_by:
            problems.add(tab, None, None, f"resource {res.id} ({res.name}) was deleted -- "
                         + MANAGED)
        elif res.activity_id not in gone:
            ch.deleted_resources.append(res)


def _crews(book, s, ch, problems):
    m, tab = book.model, book.tab("crews")
    members = {mem.id: (mem, c) for c in m.crews for mem in c.members}
    blocks = _singletons(book, [b.line for b in s.crews], lambda x: x.id,
                         [c.id for c in m.crews], lambda k: f"crew {k}", "crews", problems)
    for crew in m.crews:
        line = blocks.get(crew.id)
        if line is None:
            continue
        F.check_export_values(book, line, crew, problems)
        block = line.crew
        edit = CrewEdit(line=line, base=crew)
        own = {}
        for row in block.members:
            if row.id not in members:
                problems.add(tab, row.row, None, FOREIGN)
                continue
            if members[row.id][1].id == crew.id:
                own.setdefault(row.id, []).append(row)
        chosen = {}
        for mid, rows in own.items():
            mem = members[mid][0]
            chosen[mid] = _choose(rows, lambda x: True,
                                  lambda x: F.equal_to_base(book, x, "MEMBER", mem))
        for row in block.members:
            if row.id not in members:
                continue
            mem, owner = members[row.id]
            if owner.id == crew.id and chosen.get(row.id) is row:
                edit.roster.append(RosterRow(row, base=mem))
            else:
                edit.roster.append(RosterRow(row, source=mem))
        edit.roster += [RosterRow(row) for row in block.typed]
        edit.roster.sort(key=lambda x: x.line.row)
        edit.removed = [mem for mem in crew.members if mem.id not in chosen]
        ch.crews.append(edit)


def classify(book, s, problems) -> Changes:
    ch = Changes(ignored=list(s.ignored))
    _fixed_rows(book, s, ch, problems)
    orig, foreign, gone = _activities(book, s, ch, problems)
    _steps(book, s, ch, foreign, gone, problems)
    _resources(book, s, ch, foreign, gone, problems)
    _crews(book, s, ch, problems)
    ch.new_steps.sort(key=lambda n: n.line.row)
    ch.new_resources.sort(key=lambda n: n.line.row)
    for line in s.stray:
        problems.add(book.tab(line.sheet), line.row, None, STRAY)
    return ch
