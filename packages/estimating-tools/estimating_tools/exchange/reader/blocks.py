"""A ``blocks`` sheet's marker and zone rules, from its declaration (engine
spec, Read: Scan and Markers). The owner block's row (ACTIVITY, CREW) opens
an occurrence; the zone is ``head`` until a child block's open marker, then
that child's name, until the last child's close marker closes the
occurrence. A child whose open marker is the owner kind is opened by the
owner row itself (a crew's members). An optional child may be skipped: the
next child's open marker is allowed straight from ``head``. A banner kind
may sit anywhere inside the occurrence. ``within`` names the flat kinds
that end an open occurrence; the contract's container kind among them
(ITEM for ACTIVITY) sets the occurrence's container id."""
from __future__ import annotations

from dataclasses import dataclass

from estimating_tools.exchange.contract import CONTAINER


@dataclass(frozen=True)
class Blocks:
    """The rules of one ``blocks`` sheet. The loader (``declaration``)
    guarantees the shape relied on here: exactly one owner block, with at
    least one child, the children chained (each closes with the next one's
    open marker, so a pure close marker is the last child's), a child the
    owner row opens first, and ``within`` naming the owner kind's container
    when the sheet has it."""
    sheet: object

    @property
    def owner(self):
        return self.sheet.owner_blocks()[0]

    @property
    def children(self) -> tuple:
        return tuple(self.sheet.blocks[n] for n in self.owner.children)

    @property
    def zones(self) -> tuple:
        return ("head",) + tuple(c.name for c in self.children)

    @property
    def within(self) -> tuple:
        return tuple(self.owner.within)

    @property
    def container(self):
        kind = CONTAINER.get(self.owner.kind)
        return kind if kind in self.within else None

    @property
    def opened_by_owner(self):
        """The child the owner row itself opens (its open marker is the owner kind)."""
        return next((c for c in self.children if c.open == self.owner.kind), None)

    @property
    def banners(self) -> tuple:
        return tuple(c.banner for c in self.children if c.banner)

    @property
    def last(self):
        return self.children[-1]

    def opens(self, kind):
        """The child block ``kind`` opens, or None (the owner kind opens none here)."""
        if kind == self.owner.kind:
            return None
        return next((c for c in self.children if c.open == kind), None)

    def closes(self, kind):
        """The child block ``kind`` closes without opening another, or None."""
        if self.opens(kind) is not None:
            return None
        return next((c for c in self.children if c.close == kind), None)

    def is_marker(self, kind) -> bool:
        return self.opens(kind) is not None or self.closes(kind) is not None

    def allowed_zones(self, kind) -> tuple:
        """The zones a marker may appear in. An open marker: ``head`` plus
        every optional child before its block, as long as no non-optional
        child sits between (that one must have been entered, so only its
        zone and the optional zones after it count). A closing marker: its
        own block's zone only."""
        child = self.opens(kind)
        if child is not None:
            zones = ["head"]
            for c in self.children:
                if c is child:
                    break
                if c.optional:
                    zones.append(c.name)
                else:
                    zones = [c.name]
            return tuple(zones)
        child = self.closes(kind)
        return (child.name,) if child is not None else ()

    def block_of_row(self, kind):
        return next((c for c in self.children if c.row == kind), None)

    def rows_named(self, kind) -> str | None:
        child = self.block_of_row(kind)
        return child.name if child else None

    @property
    def optional_head_rows(self) -> tuple:
        """Row kinds of an optional child that may be typed in ``head``
        before any marker shows whether the occurrence has that block."""
        return tuple(c.row for c in self.children if c.optional and c.row)
