"""Data types every pack and the CLI share. Nothing here knows a layout."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

#: What ``Pack.detect`` says about a book: the Navigator's ``stamp.js`` kinds,
#: so the Python and JavaScript sides agree. ``none``: not this pack's book;
#: ``ok``: this pack reads it; ``newer``: this pack's book from a later pack
#: version; ``bad``: this pack's book, damaged.
Verdict = Literal["none", "ok", "newer", "bad"]


class NotYet(NotImplementedError):
    """A pack method this pack does not implement yet. The message says what
    to use instead."""


#: What a build refusal is about, so the CLI prefixes it the same for every
#: pack: ``payload`` (the read model), ``style`` (a style pack), ``profile``
#: (the org profile), ``host`` (a malformed host), ``template`` (a template
#: pack's workbook).
BUILD_REFUSAL_KINDS = ("payload", "style", "profile", "host", "template")


class BuildRefused(ValueError):
    """A pack cannot build from what it was given. ``kind`` is one of
    ``BUILD_REFUSAL_KINDS``; the message says what to fix. The generic CLI
    maps it to exit 1 and never imports a pack's own error types."""

    def __init__(self, kind: str, message: str):
        if kind not in BUILD_REFUSAL_KINDS:
            raise ValueError(f"unknown build refusal kind {kind!r}")
        self.kind = kind
        super().__init__(message)


@runtime_checkable
class ChangeSet(Protocol):
    """What ``Pack.read`` returns inside ``ReadResult`` and the CLI relies on:
    the contract's ``ops``, the ``rows`` map from op index to the sheet and
    row that produced it (``{"op_index", "sheet", "row"}``; ``row`` None
    for a deleted row), the estimate id, the printout and the JSON written
    to ``BOOK.changes.json``."""
    estimate_id: object
    ops: list
    rows: list

    def text(self) -> str: ...

    def as_json(self) -> dict: ...


@dataclass(frozen=True)
class BookFacts:
    """What detection reads from a book in one pass: custom document
    properties, the first cell of each requested defined name, sheet names."""
    path: str
    properties: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)       # defined name -> first cell's value
    sheets: list = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True)
class InsertKind:
    """A row kind a tool may insert, and the defined name of its prototype rows."""
    kind: str
    name: str


@dataclass
class ReadResult:
    """A read is a change set or a refusal, never both. ``change_set`` is a
    ``ChangeSet`` (the protocol above); ``problems`` is a list of strings
    the CLI prints one per line."""
    change_set: object = None
    problems: list = field(default_factory=list)

    def __post_init__(self):
        if (self.change_set is None) == (not self.problems):
            raise ValueError("a ReadResult is a change set or a list of problems")

    @property
    def refused(self) -> bool:
        return bool(self.problems)


def _split_ref(ref) -> tuple[str, int]:
    kind, sep, ident = str(ref).partition(":")
    if not (kind and sep and ident.isdigit()):
        raise ValueError(f"the server plan has a malformed ref {ref!r}; expected 'kind:id'")
    return kind, int(ident)


@dataclass(frozen=True)
class ApplyResult:
    """BidSheet.ai's plan, in the shape ``patch`` needs. ``created`` maps the
    change set's ``new:`` tokens to ``(kind, id)``; ``versions`` maps
    ``(kind, id)`` to the row's ``v`` after the apply (present when the
    server sends them; empty otherwise, and ``patch`` then fetches)."""
    dry_run: bool
    created: dict
    versions: dict
    deleted: list
    warnings: list
    totals: dict
    request_id: str | None = None
    replayed: bool = False
    raw: dict = field(default_factory=dict, compare=False)

    @classmethod
    def from_plan(cls, plan: dict, *, dry_run: bool) -> ApplyResult:
        for key, want, name in (("created", dict, "an object"), ("versions", dict, "an object"),
                                ("totals", dict, "an object"), ("deleted", list, "a list"),
                                ("warnings", list, "a list")):
            if plan.get(key) is not None and not isinstance(plan[key], want):
                raise ValueError(f"the server plan's {key} is not {name}")
        created = {tok: _split_ref(ref) for tok, ref in (plan.get("created") or {}).items()}
        versions = {_split_ref(ref): v for ref, v in (plan.get("versions") or {}).items()}
        return cls(dry_run=dry_run, created=created, versions=versions,
                   deleted=list(plan.get("deleted") or []),
                   warnings=list(plan.get("warnings") or []),
                   totals=dict(plan.get("totals") or {}),
                   request_id=plan.get("request_id"),
                   replayed=bool(plan.get("replayed", False)), raw=dict(plan))


@dataclass(frozen=True)
class PatchReport:
    """What a patch wrote back into the book. ``problems``: what the patch
    could not write (each says what to do, usually rebuild the book); the
    rest of the patch was written. ``notes``: what the estimator should know
    and need not act on (a Checks row with no figure any more, changes taken
    from BidSheet.ai)."""
    cells_written: int
    rows_tagged: int
    baseline_replaced: bool
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    #: Cells outside the stamp sheet were written: formulas reading them hold
    #: stale cached values until the book is recalculated (#370).
    recalc: bool = False

    def text(self) -> str:
        """The CLI's printout: the counts, then (as ``ChangeSet.text`` lists
        its notes) what was not written, then the notes, one indented line
        each."""
        base = "baseline replaced" if self.baseline_replaced else "baseline unchanged"
        lines = [f"{self.rows_tagged} row(s) tagged, {self.cells_written} cell(s) written, "
                 f"{base}"]
        if self.problems:
            lines += ["", "Not written:"] + [f"  {p}" for p in self.problems]
        if self.notes:
            lines += ["", "Notes:"] + [f"  {n}" for n in self.notes]
        return "\n".join(lines)


@dataclass(frozen=True)
class Collision:
    """A row changed in BidSheet.ai and in the book since the book's baseline
    (or deleted on one side and edited or copied on the other): ``sheet``
    and ``row`` say where (``row`` None for a row the book deleted),
    ``message`` what each side holds. Refresh reports it and writes nothing;
    the estimator decides (engine spec, "Error handling")."""
    sheet: str | None
    row: int | None
    message: str

    def __str__(self) -> str:
        where = f"{self.sheet} row {self.row}" if self.row is not None else (self.sheet or "")
        return f"{where}: {self.message}" if where else self.message


@dataclass(frozen=True)
class RefreshExtras:
    """A pack's own part of a new baseline (``Pack.refresh_extras``): value
    cells (``{tab: {ref: value}}``) on sheets no row op moves, changes the
    book cannot take in place (``structural``: each ends in what to do),
    ``notes``, and whether the cells feed formulas (``recalc``)."""
    cells: dict = field(default_factory=dict)
    structural: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    recalc: bool = False


@dataclass(frozen=True)
class RefreshReport:
    """What a refresh did, or would do (``dry_run``). Clean (no
    ``collisions``, no ``structural``): ``written`` lists each change taken
    from BidSheet.ai, and the baseline was replaced unless a dry run. Not
    clean: nothing was written and the baseline stays. ``current``: the
    book's baseline already is BidSheet.ai's estimate."""
    dry_run: bool
    baseline_replaced: bool
    cells_written: int = 0
    rows_added: int = 0
    rows_removed: int = 0
    written: list = field(default_factory=list)
    collisions: list = field(default_factory=list)
    structural: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    current: bool = False

    @property
    def clean(self) -> bool:
        return not self.collisions and not self.structural

    def text(self) -> str:
        """The CLI's printout: one head line, then what was (or would be)
        written, the collisions, the changes that need a rebuild, the notes."""
        if self.current:
            lines = ["the book is current with BidSheet.ai -- nothing to write"]
        elif not self.clean:
            lines = [f"refresh found {len(self.collisions)} row(s) changed on both sides and "
                     f"{len(self.structural)} change(s) this book cannot take in place -- "
                     "nothing written; the book keeps its baseline"]
        else:
            counts = (f"{self.cells_written} cell(s), {self.rows_added} row(s) added, "
                      f"{self.rows_removed} removed")
            lines = [f"dry run -- would write {counts}; nothing written" if self.dry_run
                     else f"refreshed -- {counts}; baseline replaced"]
            lines += [f"  {w}" for w in self.written]
        if self.collisions:
            lines += ["", "Changed in BidSheet.ai and in this book (nothing written):"]
            lines += [f"  {c}" for c in self.collisions]
        if self.structural:
            lines += ["", "Needs a rebuild (BidSheet.ai changed what this book is built "
                          "around):"]
            lines += [f"  {s}" for s in self.structural]
        if self.notes:
            lines += ["", "Notes:"] + [f"  {n}" for n in self.notes]
        return "\n".join(lines)


@dataclass(frozen=True)
class BuildReport:
    """Where a build wrote the book, and the export time it stamped."""
    path: Path
    exported_at: str
