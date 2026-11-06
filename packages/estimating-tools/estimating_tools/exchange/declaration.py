"""A pack's declaration (engine spec, Layer 2): what the book's sheets,
tags, blocks, markers, bound fields, prototypes and named rows are, as pure
data. ``load`` validates a document against ``schema/declaration.schema.json``
and the rules the schema cannot say (every bound field is writable for its
kind and sits on a visible column, fields, formulas, export values and
written text bind kinds of their sheet, a growable kind lives in a block,
a kind keyed by more than its id has its tags, tags are hidden and share no
column, markers name their owner, a sheet with resources has a ``ref`` tag,
growable kinds have prototypes and bind their ``name``, derived
tags belong to block rows and markers, a ``rates`` sheet names its four
columns and at least one rate-kind section, the named rows hold one
ESTIMATE row and no other contract kind, a ``blocks`` sheet has exactly one
owner block with at least one child, its children chained by their markers,
a child the owner row opens first, each child's ``row`` a kind the read
model collects, and ``within`` -- an owner block's alone -- naming flat
kinds of the sheet, the owner kind's container among them when the sheet
lists it), and returns a ``Declaration`` the reader and the Navigator
consume. The ``Declaration`` does not depend on
the document's key order: the stamp sorts keys, so ``visible`` orders
columns by letter and ``growable`` by the contract's table.
``lift_layout_map`` turns fieldbook's ``layout_map:`` into a declaration
without a file move."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

from estimating_tools.exchange import contract

SCHEMA_VERSION = 1


class DeclarationError(ValueError):
    """A declaration this package cannot use; the message names the key."""


def _col_index(letters: str) -> int:
    """A column's index from its letters: A=1 ... Z=26, AA=27, AB=28 ..."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


@dataclass(frozen=True)
class PackId:
    name: str
    version: str
    contract: str


@dataclass(frozen=True)
class Tag:
    column: str
    derived: tuple = ()


@dataclass(frozen=True)
class Marker:
    kind: str
    cue: tuple | None = None          # (column, text)


@dataclass(frozen=True)
class Block:
    name: str
    kind: str | None = None           # the owner kind (ACTIVITY, CREW); None for a child block
    row: str | None = None            # the row kind a child block holds
    open: str | None = None           # child block markers; ``open`` may be the owner kind
    close: str | None = None
    optional: bool = False
    fixed: bool = False
    recursive: bool = False
    banner: str | None = None
    children: tuple = ()
    within: tuple = ()                # owner block: the flat kinds that end an open occurrence


@dataclass(frozen=True)
class NamedRow:
    name: str
    kind: str
    input: bool = False
    formula: bool = False


@dataclass(frozen=True)
class NamedRows:
    name_column: str
    value_column: str
    rows: dict


@dataclass(frozen=True)
class Sheet:
    key: str
    tab: str
    role: str
    first_row: int = 1
    header_row: int | None = None
    columns: dict = field(default_factory=dict)        # visible letter -> heading
    tags: dict = field(default_factory=dict)           # tag name -> Tag
    rows: tuple = ()                                   # flat kinds
    blocks: dict = field(default_factory=dict)         # name -> Block
    markers: dict = field(default_factory=dict)        # kind -> Marker
    fields: dict = field(default_factory=dict)         # kind -> {field: letter}
    export_values: dict = field(default_factory=dict)  # kind -> {letter: attr}
    formulas: dict = field(default_factory=dict)       # "KIND" | "KIND.qualifier" | "*" -> letters
    written: dict = field(default_factory=dict)        # kind -> {letter: text}
    named_rows: NamedRows | None = None
    columns_by_key: dict = field(default_factory=dict)  # rates: key -> letter
    sections: dict = field(default_factory=dict)        # rates: kind -> title

    def tag(self, name: str) -> str | None:
        t = self.tags.get(name)
        return t.column if t else None

    def owner_blocks(self) -> list:
        return [b for b in self.blocks.values() if b.kind]

    def child_blocks(self) -> list:
        return [b for b in self.blocks.values() if b.row]

    def kinds(self) -> dict:
        """Every kind on the sheet -> how it is classed: ``row``, ``owner``,
        ``child``, ``marker``, ``banner`` or ``named``."""
        out = {k: "row" for k in self.rows}
        for b in self.blocks.values():
            if b.kind:
                out[b.kind] = "owner"
            if b.row:
                out[b.row] = "child"
            if b.banner:
                out[b.banner] = "banner"
            for m in (b.open, b.close):
                if m and m not in out:
                    out[m] = "marker"
        for m in self.markers:
            out.setdefault(m, "marker")
        if self.named_rows:
            for nr in self.named_rows.rows.values():
                out.setdefault(nr.kind, "named")
        return out


@dataclass(frozen=True)
class Declaration:
    schema: int
    pack: PackId
    kind: str
    sheets: dict
    prototypes: dict = field(default_factory=dict)
    navigator: dict = field(default_factory=dict)
    stamp: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict, compare=False)

    def tab(self, key: str) -> str:
        return self.sheets[key].tab

    def visible(self, key: str) -> tuple:
        """The visible column letters of ``key`` in column order (A ... Z, AA,
        AB ...), whatever order the document -- or the stamp, which sorts its
        keys -- lists them in."""
        return tuple(sorted(self.sheets[key].columns, key=_col_index))

    def growable(self, key: str) -> tuple:
        """The kinds a book may grow on ``key``, in ``contract.GROWABLE`` order,
        ``fixed`` ones left out. An owner block's kind counts when the contract
        lists it, whether or not the block is recursive."""
        found = set()
        for b in self.sheets[key].blocks.values():
            if b.fixed:
                continue
            found.update(k for k in (b.kind, b.row) if k)
        return tuple(k for k in contract.GROWABLE if k in found)

    def row_kinds(self) -> dict:
        """``{sheet key: {"kind_cell": letter, "kinds": {kind: {tag: letter}}}}`` for
        every sheet with a kind tag -- the shape HeavyBook's reader scans by."""
        out = {}
        for key, sheet in self.sheets.items():
            kind_cell = sheet.tag("kind")
            if kind_cell is None:
                continue
            kinds = {}
            for kind, cls in sheet.kinds().items():
                names = contract.tags_for(kind, marker=cls in ("marker", "banner"),
                                          named=cls == "named")
                kinds[kind] = {n: sheet.tag(n) for n in names if sheet.tag(n)}
            out[key] = {"kind_cell": kind_cell, "kinds": kinds}
        return out

    def size(self) -> int:
        return len(json.dumps(self.raw, sort_keys=True, separators=(",", ":")))


def _schema() -> dict:
    return json.loads(resources.files("estimating_tools.exchange").joinpath(
        "schema/declaration.schema.json").read_text(encoding="utf-8"))


def _validate(doc) -> None:
    try:
        import jsonschema
    except ImportError:
        raise DeclarationError("jsonschema is not installed; install estimating_tools (it is a "
                               "base dependency) or estimating_tools[plugin-core]") from None

    try:
        jsonschema.validate(doc, _schema())
    except jsonschema.ValidationError as exc:
        where = ".".join(str(p) for p in exc.absolute_path) or "the document"
        raise DeclarationError(f"{where}: {exc.message}") from None


def _tag(value) -> Tag:
    if isinstance(value, str):
        return Tag(column=value)
    return Tag(column=value["column"], derived=tuple(value.get("derived") or ()))


def _sheet(key: str, raw: dict) -> Sheet:
    blocks = {name: Block(name=name, kind=b.get("kind"), row=b.get("row"),
                          open=(b.get("marker") or {}).get("open"),
                          close=(b.get("marker") or {}).get("close"),
                          optional=bool(b.get("optional")), fixed=bool(b.get("fixed")),
                          recursive=bool(b.get("recursive")), banner=b.get("banner"),
                          children=tuple(b.get("children") or ()),
                          within=tuple(b.get("within") or ()))
              for name, b in (raw.get("blocks") or {}).items()}
    markers = {kind: Marker(kind=kind, cue=((m.get("cue") or {}).get("column"),
                                            (m.get("cue") or {}).get("text"))
                            if m.get("cue") else None)
               for kind, m in (raw.get("markers") or {}).items()}
    named = raw.get("named_rows")
    named_rows = None
    if named:
        named_rows = NamedRows(name_column=named["name_column"], value_column=named["value_column"],
                               rows={n: NamedRow(name=n, kind=r["kind"], input=bool(r.get("input")),
                                                 formula=bool(r.get("formula")))
                                     for n, r in named["rows"].items()})
    return Sheet(key=key, tab=raw["tab"], role=raw["role"], first_row=int(raw.get("first_row", 1)),
                 header_row=raw.get("header_row"), columns=dict(raw.get("columns") or {}),
                 tags={n: _tag(t) for n, t in (raw.get("tags") or {}).items()},
                 rows=tuple(raw.get("rows") or ()), blocks=blocks, markers=markers,
                 fields={k: dict(v) for k, v in (raw.get("fields") or {}).items()},
                 export_values={k: dict(v) for k, v in (raw.get("export_values") or {}).items()},
                 formulas={k: tuple(v) for k, v in (raw.get("formulas") or {}).items()},
                 written={k: dict(v) for k, v in (raw.get("written") or {}).items()},
                 named_rows=named_rows, columns_by_key=dict(raw.get("columns_by_key") or {}),
                 sections=dict(raw.get("sections") or {}))


def _check_sheet(sheet: Sheet, prototypes: dict) -> None:
    at = f"sheets.{sheet.key}"
    kinds = sheet.kinds()
    tag_columns = {t.column for t in sheet.tags.values()}
    if sheet.role in ("blocks", "flat") and sheet.tag("kind") is None:
        raise DeclarationError(f"{at}.tags: a {sheet.role} sheet needs a kind tag")
    # Rows: a kind the book may grow lives in a block, never as a flat row.
    for kind in sheet.rows:
        if kind in contract.GROWABLE:
            raise DeclarationError(f"{at}.rows: {kind} is a growable kind; declare it in a block")
    # Tags: hidden, one column each.
    by_column = {}
    for name, t in sheet.tags.items():
        if t.column in sheet.columns:
            raise DeclarationError(f"{at}.tags.{name}: {t.column} is a visible column; "
                                   "tags are hidden")
        if t.column in by_column:
            raise DeclarationError(f"{at}.tags: {by_column[t.column]} and {name} share column "
                                   f"{t.column}")
        by_column[t.column] = name
    # Identity: named rows are found by name (checked first, so a missing
    # name tag is reported as that, not as a named kind's missing tag); then
    # every contract kind on the sheet has the tags the table lists, and a
    # marker or banner row names its owner.
    if sheet.named_rows:
        if sheet.tag("name") is None:
            raise DeclarationError(f"{at}.tags: named rows need a name tag")
        if sheet.named_rows.name_column != sheet.tag("name"):
            raise DeclarationError(f"{at}.named_rows.name_column: must be the name tag column "
                                   f"{sheet.tag('name')}")
    for kind in kinds:
        for name in contract.TAGS.get(kind, ()):
            if sheet.tag(name) is None:
                raise DeclarationError(f"{at}.tags: {kind} needs a {name} tag")
    if any(cls in ("marker", "banner") for cls in kinds.values()) and sheet.tag("parent") is None:
        raise DeclarationError(f"{at}.tags: markers need a parent tag")
    # A resource row carries its rate link in the ref tag (contract rule 11:
    # the link travels with a pasted row).
    if any(b.row == "RESOURCE" for b in sheet.blocks.values()) and sheet.tag("ref") is None:
        raise DeclarationError(f"{at}.tags: a sheet with resources needs a ref tag (rate links, "
                               "contract rule 11)")
    # Named rows: one ESTIMATE row (the estimate's identity), the rest
    # layout-only kinds without tags, never another contract kind.
    if sheet.named_rows:
        estimate_rows = [n for n, r in sheet.named_rows.rows.items() if r.kind == "ESTIMATE"]
        if len(estimate_rows) > 1:
            a, b = estimate_rows[:2]
            raise DeclarationError(f"{at}.named_rows: one ESTIMATE row ({a} and {b})")
        for name, r in sheet.named_rows.rows.items():
            if r.kind in contract.TAGS and r.kind != "ESTIMATE":
                raise DeclarationError(f"{at}.named_rows.{name}: {r.kind} is not a named-row kind")
    # A rates sheet: the four columns the reader compares and at least one
    # section, each a contract rate kind.
    if sheet.role == "rates":
        if any(k not in sheet.columns_by_key for k in ("id", "name", "unit", "rate")):
            raise DeclarationError(f"{at}.columns_by_key: a rates sheet needs id, name, unit "
                                   "and rate")
        for kind in sheet.sections:
            if kind not in contract.RATE_KINDS:
                raise DeclarationError(f"{at}.sections: {kind} is not a rate kind (known: "
                                       f"{', '.join(contract.RATE_KINDS)})")
        if not sheet.sections:
            raise DeclarationError(f"{at}.sections: a rates sheet needs at least one section")
    # Fields: on a kind of this sheet, writable, once per kind, on a visible
    # column (never a tag column).
    for kind, bound in sheet.fields.items():
        if kind not in kinds:
            raise DeclarationError(f"{at}.fields.{kind}: {kind} is not a row kind of this sheet")
        allowed = contract.FIELDS.get(kind)
        if allowed is None:
            raise DeclarationError(f"{at}.fields.{kind}: not a contract kind with writable fields")
        seen = {}
        for name, letter in bound.items():
            if name not in allowed:
                raise DeclarationError(f"{at}.fields.{kind}.{name}: not writable for {kind} "
                                       f"(writable: {', '.join(allowed)})")
            if letter in tag_columns:
                raise DeclarationError(f"{at}.fields.{kind}.{name}: {letter} is a tag column")
            if letter not in sheet.columns:
                raise DeclarationError(f"{at}.fields.{kind}.{name}: {letter} is not a visible column")
            if letter in seen:
                raise DeclarationError(f"{at}.fields.{kind}: column {letter} twice "
                                       f"({seen[letter]} and {name})")
            seen[letter] = name
    # Export values and written text bind kinds of this sheet.
    for section in ("export_values", "written"):
        for kind in getattr(sheet, section):
            if kind not in kinds:
                raise DeclarationError(f"{at}.{section}.{kind}: {kind} is not a row kind of "
                                       "this sheet")
    # Blocks: a block is an owner (``kind``) or a child (``row``); exactly
    # one owner block per blocks sheet (its row opens the occurrence the
    # scanner walks), with at least one child; ``within`` is
    # the owner block's and names flat kinds of the sheet, the owner kind's
    # container among them when the sheet lists it; a child block's row is
    # a kind the read model collects; child blocks have markers; markers are
    # declared; a child the owner row opens is the first; the children
    # chain, each closing with the next one's open marker (so a pure close
    # marker is the last child's).
    owner_blocks = sheet.owner_blocks()
    if len(owner_blocks) > 1:
        names = [b.name for b in owner_blocks]
        raise DeclarationError(f"{at}.blocks: one owner block per sheet (found {', '.join(names)})")
    if sheet.role == "blocks" and not owner_blocks:
        raise DeclarationError(f"{at}.blocks: a blocks sheet needs an owner block")
    owners = {o.kind for o in owner_blocks}
    for b in sheet.blocks.values():
        if not b.kind and not b.row:
            raise DeclarationError(f"{at}.blocks.{b.name}: a block is an owner (kind) or a "
                                   "child (row)")
        if b.within and not b.kind:
            raise DeclarationError(f"{at}.blocks.{b.name}.within: only an owner block ends on "
                                   "other rows")
        for k in b.within:
            if k not in sheet.rows:
                raise DeclarationError(f"{at}.blocks.{b.name}.within: {k} is not a row kind of "
                                       "the sheet")
        if b.kind:
            container = contract.CONTAINER.get(b.kind)
            if container in sheet.rows and container not in b.within:
                raise DeclarationError(f"{at}.blocks.{b.name}.within: must list {container}, "
                                       "the kind its rows sit under")
            if not b.children:
                raise DeclarationError(f"{at}.blocks.{b.name}: an owner block needs a child block")
        if b.row and b.row not in contract.COLLECTIONS:
            raise DeclarationError(f"{at}.blocks.{b.name}.row: {b.row} is not a block row kind "
                                   f"(known: {', '.join(contract.COLLECTIONS)})")
        for child in b.children:
            if child not in sheet.blocks:
                raise DeclarationError(f"{at}.blocks.{b.name}.children: no block named {child}")
        if b.row and not (b.open and b.close):
            raise DeclarationError(f"{at}.blocks.{b.name}: a row block needs open and close markers")
        for m in (b.open, b.close):
            if m and m not in sheet.markers and m not in owners:
                raise DeclarationError(f"{at}.blocks.{b.name}: marker {m} is not declared under markers")
    for owner in owner_blocks:
        children = [sheet.blocks[n] for n in owner.children]
        for i, c in enumerate(children):
            if c.open == owner.kind and i > 0:
                raise DeclarationError(f"{at}.blocks.{c.name}: a block the owner row opens must "
                                       "be its first child")
        for c, following in zip(children, children[1:]):
            if c.close != following.open:
                raise DeclarationError(f"{at}.blocks.{owner.name}: child {c.name} must close with "
                                       f"{following.name}'s open marker ({following.open})")
    for m in sheet.markers.values():
        if m.cue and m.cue[0] not in sheet.columns:
            raise DeclarationError(f"{at}.markers.{m.kind}.cue: column {m.cue[0]} is not visible")
    # Derived tags belong to block rows and markers, never to an owner kind.
    for name, t in sheet.tags.items():
        for kind in t.derived:
            if kind in owners:
                raise DeclarationError(f"{at}.tags.{name}.derived: {kind} opens a block; its "
                                       f"{name} is stored, not derived")
            if kinds.get(kind) not in ("child", "marker", "banner"):
                raise DeclarationError(f"{at}.tags.{name}.derived: {kind} is not a block row or marker")
    # Formulas: kinds of this sheet (or ``*``), qualifiers the engine knows.
    # The letters are not checked: a formula may sit in a hidden column.
    for entry in sheet.formulas:
        if entry == "*":
            continue
        kind, _, qual = entry.partition(".")
        if kind not in kinds:
            raise DeclarationError(f"{at}.formulas.{entry}: {kind} is not a row kind of this sheet")
        if qual and qual not in contract.QUALIFIERS:
            raise DeclarationError(f"{at}.formulas.{entry}: unknown qualifier {qual!r} "
                                   f"(known: {', '.join(contract.QUALIFIERS)})")
    # Prototypes: every growable kind (an owner block's kind included, when
    # the contract lists it) unless its block is fixed. A growable kind
    # whose contract fields include ``name`` binds it: a new row is created
    # from its name.
    for b in sheet.blocks.values():
        if b.fixed:
            continue
        for kind in (b.kind, b.row):
            if kind not in contract.GROWABLE:
                continue
            if kind.lower() not in prototypes:
                raise DeclarationError(f"{at}.blocks.{b.name}: no prototype for {kind} "
                                       f"(prototypes.{kind.lower()}), and the block is not fixed")
            if "name" in contract.FIELDS.get(kind, {}) and "name" not in sheet.fields.get(kind, {}):
                raise DeclarationError(f"{at}.fields.{kind}: a growable kind needs its name bound")


def load(doc: dict) -> Declaration:
    """A ``Declaration`` from its document, or ``DeclarationError``."""
    if not isinstance(doc, dict):
        raise DeclarationError("the declaration is not an object")
    if doc.get("schema") != SCHEMA_VERSION:
        raise DeclarationError(f"schema {doc.get('schema')!r}: this reader knows schema "
                               f"{SCHEMA_VERSION}; update the plugin")
    _validate(doc)
    prototypes = dict(doc.get("prototypes") or {})
    sheets = {key: _sheet(key, raw) for key, raw in doc["sheets"].items()}
    for sheet in sheets.values():
        _check_sheet(sheet, prototypes)
    p = doc["pack"]
    return Declaration(schema=SCHEMA_VERSION, pack=PackId(p["name"], p["version"], p["contract"]),
                       kind=doc["kind"], sheets=sheets, prototypes=prototypes,
                       navigator=dict(doc.get("navigator") or {}), stamp=dict(doc.get("stamp") or {}),
                       raw=doc)


def lift_layout_map(layout_map: dict, *, pack: str, version: str, contract_major: str = "1") -> dict:
    """Fieldbook's ``layout_map:`` as a declaration document: the Navigator
    section is the map's tables and cells; the prototypes are the task row
    and the map's template rows under ``est.tpl.*`` (the rows
    ``FieldbookPack.templates`` names); no sheet binds a field (roadmap 1.11)."""
    templates = ((layout_map.get("templates") or {}).get("rows") or {})
    return {"schema": SCHEMA_VERSION,
            "pack": {"name": pack, "version": version, "contract": contract_major},
            "kind": "recipe",
            "prototypes": {key: f"est.tpl.{key}" for key in ("task", *templates)},
            "navigator": {"tables": dict(layout_map.get("tables") or {}),
                          "cells": dict(layout_map.get("cells") or {}),
                          "tags": dict(layout_map.get("tags") or {}),
                          "blocks": dict(layout_map.get("blocks") or {})},
            "sheets": {}}
