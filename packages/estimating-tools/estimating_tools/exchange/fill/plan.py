"""Where every row of a template fill goes (engine spec, Fill step 2): the
read model walked in the declaration's order, one ``Row`` per book row,
decided before anything is written. ``regions`` gives each sheet's rows per
fill region (``[(template row, rows)]``); ``layout`` all of them.

A ``blocks`` sheet fills from ``first_row``. An ACTIVITY sheet: per item
(payload order), the container row when the sheet lists the container kind
(``contract.CONTAINER``: ITEM), the rows the read model nests under it
(``contract.UNDER``: its element quantities, in element display order, then
key), then its root activities (sort order, id), each as its block
prototype's rows -- the owner row, each child block's open marker, one copy
of the sample row per child row (none for a child without rows), the close
marker -- followed by its child activities, depth first. Quantities that pay
no item close the sheet under a GROUP row. A CREW sheet: each crew (payload
order) as its block, members by sort order, classification and id. An owner
is copied from a variant prototype when the read model says so
(``contract.VARIANT_WHEN``: a stepped activity, a library crew) and the
template has that variant (a required STEP block is in the plain prototype,
so every activity is stepped).

A ``flat`` sheet fills each region from ``display.FLAT`` (bid lines, bid
totals), one copy of its kind's own prototype per row. A ``display`` or
``rates`` sheet fills each region from ``display.SOURCES``, kind by kind:
per object, its prototype's rows (``KIND.variant`` when a variant's
predicate holds, first in the sheet's prototype order), a row whose kind is
one of the source's children repeated per child.

Outline levels follow the tree: a container row 0, its nested rows 1, an
owner row 1 plus its depth, its block rows one deeper. A block's owner and
marker rows are named in every one of its rows' ``block`` map, so the
owner's formulas over its brackets read its own placed brackets
(``refs.place``); a display or flat row reads its own row only."""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.exchange import contract, display
from estimating_tools.exchange.fill.lint import is_stepped
from estimating_tools.exchange.reader.blocks import Blocks

__all__ = ["FillRefused", "Row", "layout", "regions"]


class FillRefused(ValueError):
    """A payload this template cannot lay out; the message says why."""


@dataclass
class Row:
    """One placed row: its kind, the prototype row it copies, the read-model
    object it shows, the occurrence owner's id (block rows), the id a
    display row stores (``ident``), whether its occurrence is stepped, its
    outline level, and ``block``: ``((prototype row, index among the
    region's rows), ...)``."""
    kind: str
    proto_row: int
    obj: object = None
    extra: dict = field(default_factory=dict)
    owner_id: object = None
    stepped: bool = False
    level: int = 0
    block: tuple = ()
    ident: object = None


def _quantities(wb):
    return [(e, q) for e in sorted(wb.elements, key=lambda e: (e.display_order, e.id))
            for q in sorted(e.quantities, key=lambda q: q.key)]


class _Sheet:
    def __init__(self, decl, key, wb, protos):
        self.decl, self.key, self.wb, self.protos = decl, key, wb, protos
        self.sheet = decl.sheets[key]
        self.rows = []

    def proto(self, key):
        found = self.protos.get(key)
        if found is None:
            raise FillRefused(f"sheets.{self.key}: the template has no {key} prototype")
        return found

    def single(self, kind, obj=None, level=0, extra=None):
        proto = self.proto(kind.lower())
        self.rows.append(Row(kind, proto.first, obj=obj, extra=dict(extra or {}), level=level))

    def occurrence(self, b, owner, depth, base):
        """One owner and its block, from its prototype, then its children."""
        kind = b.owner.kind
        variants = contract.VARIANTS.get(kind, {})
        children = {c.row: self.children_of(c.row, owner) for c in b.children}
        # A variant where the read model says so and the template has it
        # (``lint.needed`` asks for one only where its row is optional: a
        # required child is in the plain prototype already).
        key = next((v for _row, v in variants.items()
                    if v in self.protos and contract.VARIANT_WHEN[v](owner)), kind.lower())
        proto = self.proto(key)
        # Stepped by the rows copied (``lint.is_stepped``), as the reader
        # reads the block back: a required STEP block steps every activity.
        stepped = is_stepped(proto.kinds)
        level = base + depth
        start = len(self.rows)
        placed = []
        for offset, row_kind in enumerate(proto.kinds):
            proto_row = proto.first + offset
            if offset == 0:
                placed.append(Row(kind, proto_row, obj=owner, level=level, stepped=stepped))
            elif row_kind in children:
                placed += [Row(row_kind, proto_row, obj=child, owner_id=owner.id,
                               level=level + 1, stepped=stepped)
                           for child in children[row_kind]]
            else:
                placed.append(Row(row_kind, proto_row, owner_id=owner.id, level=level + 1,
                                  stepped=stepped))
        # The owner and markers stand for their prototype rows in every
        # formula of the block.
        bracket = tuple((p.proto_row, start + i) for i, p in enumerate(placed)
                        if self.sheet.kinds().get(p.kind) in ("owner", "marker"))
        for p in placed:
            p.block = bracket
        self.rows += placed
        if b.owner.recursive:
            for child in self.wb.children(owner.id):
                self.occurrence(b, child, depth + 1, base)

    def children_of(self, row_kind, owner):
        if row_kind == "STEP":
            return list(owner.steps)
        if row_kind == "RESOURCE":
            return list(self.wb.resources_of(owner.id))
        if row_kind == "MEMBER":
            return sorted(owner.members, key=lambda m: (m.sort_order, m.classification, m.id))
        raise FillRefused(f"the fill cannot lay out {row_kind} rows")

    def blocks(self):
        b = Blocks(self.sheet)
        if b.owner.kind == "CREW":
            for crew in self.wb.crews:
                self.occurrence(b, crew, 0, 0)
            return self.rows
        if b.owner.kind != "ACTIVITY":
            raise FillRefused(f"sheets.{self.key}: the fill lays out ACTIVITY and CREW owner "
                              f"blocks, not {b.owner.kind}")
        rows = self.sheet.rows
        container = b.container
        quantities = _quantities(self.wb)
        base = 1 if container else 0
        for item in self.wb.items:
            if container:
                self.single("ITEM", item, 0)
            if "ELEMENT_QTY" in rows:
                for e, q in quantities:
                    if q.pay_item_id == item.id:
                        self.single("ELEMENT_QTY", q, 1, {"element": e})
            for root in self.wb.roots(item.id):
                self.occurrence(b, root, 0, base)
        if "ELEMENT_QTY" in rows:
            unpaid = [(e, q) for e, q in quantities if q.pay_item_id is None]
            if unpaid and "GROUP" not in rows:
                raise FillRefused(f"sheets.{self.key}: {len(unpaid)} element quantities pay no "
                                  "item and the sheet has no GROUP row to list them under")
            if unpaid:
                self.single("GROUP", None, 0)
                for e, q in unpaid:
                    self.single("ELEMENT_QTY", q, 1, {"element": e})
        return self.rows

    def display_block(self, kind, obj) -> list:
        src = display.SOURCES[kind]
        variant = next((k.partition(".")[2] for k in self.sheet.prototypes
                        if k.startswith(kind + ".")
                        and src.variants[k.partition(".")[2]](self.wb, obj)), None)
        proto = self.proto(f"{self.key}:{kind}" + (f".{variant}" if variant else ""))
        placed = []
        for offset, row_kind in enumerate(proto.kinds):
            proto_row = proto.first + offset
            if row_kind in src.children:
                _cls, children = src.children[row_kind]
                placed += [Row(row_kind, proto_row, obj=child, ident=display.child_ident(child))
                           for child in children(self.wb, obj)]
            else:
                placed.append(Row(row_kind, proto_row, obj=obj, ident=src.ident(obj)))
        return placed

    def region(self, region) -> list:
        rows = []
        if self.sheet.role == "flat":
            for kind, obj in display.FLAT[tuple(region.rows)](self.wb):
                rows.append(Row(kind, self.proto(f"{self.key}:{kind}").first, obj=obj))
            return rows
        for kind in region.rows:
            for obj in display.SOURCES[kind].rows(self.wb, self.sheet):
                rows += self.display_block(kind, obj)
        return rows


def regions(decl, key, wb, protos) -> list:
    """``[(template row, rows)]`` for sheet ``key``, top to bottom: a blocks
    sheet's one region at ``first_row``, a flat, rates or display sheet's
    declared ones. ``FillRefused`` for a payload the template cannot lay
    out."""
    sheet = _Sheet(decl, key, wb, protos)
    s = decl.sheets[key]
    if s.role == "blocks":
        return [(s.first_row, sheet.blocks())]
    return [(r.at, sheet.region(r)) for r in s.regions]


def layout(decl, key, wb, protos) -> list:
    """Every row of sheet ``key``, top to bottom (``Row``)."""
    return [row for _at, rows in regions(decl, key, wb, protos) for row in rows]
