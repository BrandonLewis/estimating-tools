"""Where a created activity or resource line goes among its siblings (#458).

``activity.create`` and ``resource.create`` store the ``sort_order`` they are
sent; BidSheet.ai never renumbers siblings (BidManager #1681), and rows list
by ``(sort_order, id)``. A created row's id is higher than every existing
row's, and the creates run in sheet order, so a created row sorts after
every sibling with the same ``sort_order`` it was sent, and after the
creates before it. The rule:

- A created row goes right after the nearest existing sibling above it on
  the sheet (its anchor), in BidSheet.ai's order; with none above, before
  the first existing sibling. Existing siblings keep their BidSheet.ai order:
  the reader never reorders a row the estimator did not create. A block
  whose existing rows the sheet lists in another order is noted
  (``reordered``, ``ops.REORDERED``) and nothing is sent for it.
- It takes its anchor's ``sort_order`` (it sorts after the anchor by id); a
  row with no anchor takes one less than the first sibling's (it may be
  negative), or 0 when the block has no existing siblings -- the rule
  Estimate Navigator's activity inserts already used.
- No gap: when the existing sibling after the anchor has the same
  ``sort_order`` (a tie, broken by id), no value places the created row
  between them. The siblings from there down are renumbered: each one that
  would sort before the row above it is sent the smallest ``sort_order``
  that keeps it after that row (``prev + 1``), so only rows that must move
  are written, and integers stay integers. A renumbered row gets an update
  op (merged into its edit, if it has one) and carries its ``v``; an
  allocation-posted line, which is never written, refuses the read instead
  (``ops.MANAGED_ORDER``).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Orders:
    """One kind's placement."""
    #: ``id(new row object)`` -> the ``sort_order`` its create sends.
    orders: dict = field(default_factory=dict)
    #: An existing sibling's id -> ``(line, before, after)``: its renumbering.
    bumps: dict = field(default_factory=dict)
    #: ``(line, row)`` per block whose existing rows the sheet lists in
    #: another order than ``(sort_order, id)``: the first row out of place.
    reordered: list = field(default_factory=list)


@dataclass
class Placement:
    activities: Orders = field(default_factory=Orders)
    resources: Orders = field(default_factory=Orders)


def place(siblings, new_rows, out: Orders):
    """Place one block's created rows. ``siblings``: the existing rows that
    stay in the block, as ``(line, row)`` (``row`` has ``id`` and
    ``sort_order``, as in the baseline); ``new_rows``: ``(object, sheet
    row)`` for each created row. Fills ``out``."""
    ordered = sorted(siblings, key=lambda s: (s[1].sort_order, s[1].id))
    by_anchor = {}
    for new, sheet_row in sorted(new_rows, key=lambda n: n[1]):
        above = [s for s in ordered if s[0].row < sheet_row]
        anchor = max(above, key=lambda s: s[0].row)[1].id if above else None
        by_anchor.setdefault(anchor, []).append(new)
    seq = [("new", n) for n in by_anchor.get(None, ())]
    for line, row in ordered:
        seq.append(("old", (line, row)))
        seq += [("new", n) for n in by_anchor.get(row.id, ())]
    first = ordered[0][1].sort_order if ordered else None
    # The previous entry's key: (sort_order, id), id None for a created row
    # (higher than any existing id; created rows tie among themselves in
    # creation order).
    last = None
    for kind, entry in seq:
        if kind == "new":
            value = (last[0] if last is not None
                     else 0 if first is None else first - 1)
            out.orders[id(entry)] = value
            last = (value, None)
            continue
        line, row = entry
        s = row.sort_order
        if last is None or s > last[0] or (s == last[0] and last[1] is not None
                                           and row.id > last[1]):
            last = (s, row.id)
            continue
        out.bumps[row.id] = (line, s, last[0] + 1)
        last = (last[0] + 1, row.id)


def reordered(siblings, out: Orders):
    """Note one block's existing rows (``(line, row)``, as for ``place``)
    when the sheet lists them in another order than BidSheet.ai's."""
    by_sheet = sorted(siblings, key=lambda s: s[0].row)
    ordered = sorted(siblings, key=lambda s: (s[1].sort_order, s[1].id))
    for (line, row), (_line, want) in zip(by_sheet, ordered):
        if row.id != want.id:
            out.reordered.append((line, row))
            return


def placement(book, ch) -> Placement:
    """Every created activity's and resource line's ``sort_order``, the
    existing siblings that must be renumbered for them, and the blocks whose
    existing rows were reordered (module doc)."""
    out = Placement()
    _activities(book, ch, out.activities)
    _resources(ch, out.resources)
    return out


def _activities(book, ch, out):
    m = book.model
    orig = {o.id: o for o in ch.activities}

    def ends_root(o):
        pid = m.activity(o.id).parent_id
        return pid is None or pid not in orig or orig[pid].item_id != o.item_id

    blocks = {}
    for o in orig.values():
        key = ("root", o.item_id) if ends_root(o) else ("child", m.activity(o.id).parent_id)
        blocks.setdefault(key, []).append((o.line, m.activity(o.id)))
    groups = {}
    for new in ch.new_activities:
        if new.occ.item_id is None:
            continue
        if new.parent is None:
            key = ("root", new.occ.item_id)
        elif isinstance(new.parent, str):
            key = ("new", new.parent)       # under a created parent: all siblings new
        else:
            key = ("child", new.parent)
        groups.setdefault(key, []).append((new, new.occ.line.row))
    for key, news in groups.items():
        place(blocks.get(key, []), news, out)
    for sibs in blocks.values():
        reordered(sibs, out)


def _resources(ch, out):
    blocks = {}
    for line, res in ch.resources:
        blocks.setdefault(id(line.occ), []).append((line, res))
    groups = {}
    for new in ch.new_resources:
        groups.setdefault(id(new.occ), []).append((new, new.line.row))
    for key, news in groups.items():
        place(blocks.get(key, []), news, out)
    for sibs in blocks.values():
        reordered(sibs, out)
