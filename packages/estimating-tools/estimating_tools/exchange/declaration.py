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
model collects, an owner block shows a child block for each row kind its
owner holds and a container's sheet lists the kinds nested under it -- or
the sheet names the kind in ``not_shown``, which only those kinds may be,
shown nowhere on the sheet and with no prototype -- a growable kind binds
what a new row is created from (``contract.CREATE_NEEDS``), and
``within`` -- an owner block's alone -- naming flat
kinds of the sheet, the owner kind's container among them when the sheet
lists it, a ``display`` sheet lays out ``display.SOURCES`` in its regions only
(a flat, rates or display sheet's regions sit top to bottom; its own
prototypes name a region kind and one of its source's variants), a label
names a path its kind has and no cell the row's tags, fields or export
values own, a header cell sits above ``first_row``), and returns a ``Declaration`` the reader and the Navigator
consume. The ``Declaration`` does not depend on
the document's key order: the stamp sorts keys, so ``visible`` orders
columns by letter and ``growable`` by the contract's table.
``kinds:`` maps a pack's own row kinds (forms: fieldbook's TASK, CREW,
LINE) to contract kinds; blocks, ``not_shown``, derived tags and ``each``
name contract kinds, and an alias written there is resolved; fields,
formulas, export values, written text, labels and prototypes name forms,
and a contract kind with forms on a sheet is bound through its forms only.
A sheet may say ``each: ITEM`` instead of a ``tab``: one tab per container
row, which ``Declaration.expand`` lays out before a read.
``lift_layout_map`` turns fieldbook's ``layout_map:`` into a declaration
without a file move."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from importlib import resources

from estimating_tools.exchange import contract, display, labels

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
class Region:
    """Where a fill lays rows out on a flat, rates or display sheet: above
    template row ``at``, the ``rows`` kinds in order."""
    at: int
    rows: tuple


@dataclass(frozen=True)
class Binding:
    """How one field is bound: a ``column`` of the row; ``cells`` of the
    row joined by ``sep`` (blank ones skipped); the ``column`` of the
    ``rows`` kind's rows in the owner's block, joined by ``sep``; the
    ``kind`` or ``rate`` of the rate the row's name picks (``from_rate``);
    or a workbook-scoped defined name (``by_name``)."""
    column: str | None = None
    cells: tuple = ()
    rows: str | None = None
    sep: str | None = None
    from_rate: str | None = None
    by_name: str | None = None

    def own_letters(self) -> tuple:
        """The cells of the bound row itself this binding reads."""
        if self.rows is None and self.column is not None:
            return (self.column,)
        return self.cells


def binding(raw) -> Binding:
    """A ``Binding`` from a field's declared value (a letter, or a form)."""
    if isinstance(raw, str):
        return Binding(column=raw)
    if "rows" in raw:
        return Binding(column=raw["column"], rows=raw["rows"], sep=raw["join"])
    if "cells" in raw:
        return Binding(cells=tuple(raw["cells"]), sep=raw["join"])
    if "from_rate" in raw:
        return Binding(from_rate=raw["from_rate"])
    return Binding(by_name=raw["by_name"])


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
    #: Tagged rates sheet: the suffix a local rate carries when a library
    #: rate has its name (fieldbook: `` (local)``).
    local_suffix: str | None = None
    labels: dict = field(default_factory=dict)          # kind -> {letter: labels.Label}
    header: dict = field(default_factory=dict)          # cell -> labels.Label
    regions: tuple = ()                                 # Region, top to bottom
    prototypes: dict = field(default_factory=dict)      # fill-only: KIND[.variant] -> name
    #: Kinds the sheet's owner or container holds that it deliberately does
    #: not show: the reader never reads or diffs them (#439).
    not_shown: tuple = ()
    #: Pack kind -> contract kind (the declaration's ``kinds:``), shared by
    #: every sheet of the declaration.
    aliases: dict = field(default_factory=dict)
    #: Field -> {the book's text: the contract's value} for coded fields.
    spellings: dict = field(default_factory=dict)
    #: The container kind this sheet repeats for: one tab per row of it
    #: (fieldbook's one sheet per bid item); ``tab`` is "" until
    #: ``Declaration.expand`` gives each copy its own.
    each: str | None = None

    def tag(self, name: str) -> str | None:
        t = self.tags.get(name)
        return t.column if t else None

    def contract_kind(self, form: str) -> str:
        """The contract kind a row tagged ``form`` is (itself, unaliased)."""
        return self.aliases.get(form, form)

    def forms(self, kind: str) -> tuple:
        """What a row of contract ``kind`` is tagged as: the pack kinds
        aliased to it, by name, or ``kind`` itself when none is."""
        found = tuple(sorted(f for f, k in self.aliases.items() if k == kind))
        return found or (kind,)

    def binding(self, form: str, name: str):
        """``name``'s ``Binding`` on rows tagged ``form``, or None."""
        raw = self.fields.get(form, {}).get(name)
        return None if raw is None else binding(raw)

    def joined(self) -> tuple:
        """The row kinds a ``rows`` join reads (fieldbook's NOTE)."""
        return tuple(dict.fromkeys(binding(raw).rows for bound in self.fields.values()
                                   for raw in bound.values()
                                   if binding(raw).rows is not None))

    def owner_blocks(self) -> list:
        return [b for b in self.blocks.values() if b.kind]

    def child_blocks(self) -> list:
        return [b for b in self.blocks.values() if b.row]

    def kinds(self) -> dict:
        """Every kind on the sheet, by the name its rows are tagged with (a
        form, for an aliased kind) -> how it is classed: ``row``, ``owner``,
        ``child``, ``marker``, ``banner``, ``joined`` or ``named``."""
        out = {k: "row" for k in self.rows}
        owners = {b.kind for b in self.blocks.values() if b.kind}
        for b in self.blocks.values():
            if b.kind:
                out.update({f: "owner" for f in self.forms(b.kind)})
            if b.row:
                out.update({f: "child" for f in self.forms(b.row)})
            if b.banner:
                out[b.banner] = "banner"
            for m in (b.open, b.close):
                # The owner kind opening its own first block is no marker.
                if m and m not in out and m not in owners:
                    out[m] = "marker"
        for kind in self.joined():
            # A contract kind is never the pack's joined rows (the binding
            # rule says so); one already classed keeps its class, so the
            # rule can name the clash.
            if kind not in contract.TAGS:
                out.setdefault(kind, "joined")
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
    #: Pack kind -> contract kind (``kinds:``).
    aliases: dict = field(default_factory=dict)
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

    def expand(self, tabs_of) -> "Declaration":
        """This declaration with each ``each`` sheet replaced by one sheet
        per tab ``tabs_of(sheet)`` names, in that order -- keys ``<key>.1``,
        ``<key>.2`` ... -- each with its own ``tab``; the other sheets as
        they are, in their order. A declaration without one is itself."""
        if not any(s.each for s in self.sheets.values()):
            return self
        sheets = {}
        for key, sheet in self.sheets.items():
            if not sheet.each:
                sheets[key] = sheet
                continue
            for n, tab in enumerate(tabs_of(sheet), 1):
                sheets[f"{key}.{n}"] = replace(sheet, key=f"{key}.{n}", tab=tab)
        return replace(self, sheets=sheets)

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
                names = contract.tags_for(sheet.contract_kind(kind),
                                          marker=cls in ("marker", "banner"),
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


def _tag(value, aliases=None) -> Tag:
    if isinstance(value, str):
        return Tag(column=value)
    derived = tuple((aliases or {}).get(k, k) for k in value.get("derived") or ())
    return Tag(column=value["column"], derived=derived)


def _label(at: str, text):
    try:
        return labels.parse(text)
    except labels.LabelError as exc:
        raise DeclarationError(f"{at}: {exc}") from None


def _sheet(key: str, raw: dict, aliases=None) -> Sheet:
    aliases = dict(aliases or {})

    def res(kind):
        return aliases.get(kind, kind) if kind else kind

    blocks = {name: Block(name=name, kind=res(b.get("kind")), row=res(b.get("row")),
                          open=res((b.get("marker") or {}).get("open")),
                          close=res((b.get("marker") or {}).get("close")),
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
    return Sheet(key=key, tab=raw.get("tab") or "", role=raw["role"],
                 first_row=int(raw.get("first_row", 1)),
                 header_row=raw.get("header_row"), columns=dict(raw.get("columns") or {}),
                 tags={n: _tag(t, aliases) for n, t in (raw.get("tags") or {}).items()},
                 rows=tuple(raw.get("rows") or ()), blocks=blocks, markers=markers,
                 fields={k: dict(v) for k, v in (raw.get("fields") or {}).items()},
                 export_values={k: dict(v) for k, v in (raw.get("export_values") or {}).items()},
                 formulas={k: tuple(v) for k, v in (raw.get("formulas") or {}).items()},
                 written={k: dict(v) for k, v in (raw.get("written") or {}).items()},
                 named_rows=named_rows, columns_by_key=dict(raw.get("columns_by_key") or {}),
                 sections=dict(raw.get("sections") or {}),
                 local_suffix=raw.get("local_suffix"),
                 labels={k: {letter: _label(f"sheets.{key}.labels.{k}.{letter}", text)
                             for letter, text in v.items()}
                         for k, v in (raw.get("labels") or {}).items()},
                 header={cell: _label(f"sheets.{key}.header.{cell}", text)
                         for cell, text in (raw.get("header") or {}).items()},
                 regions=tuple(Region(int(r["at"]), tuple(r["rows"]))
                               for r in raw.get("regions") or ()),
                 prototypes=dict(raw.get("prototypes") or {}),
                 not_shown=tuple(res(k) for k in raw.get("not_shown") or ()),
                 spellings={k: dict(v) for k, v in (raw.get("spellings") or {}).items()},
                 each=res(raw.get("each")),
                 aliases=aliases)


def _check_regions(sheet, at):
    """Regions sit top to bottom; a display or rates region lays out
    ``display.SOURCES`` kinds, each source once, a flat one a
    ``display.FLAT`` row set, each of the sheet's rows once; a per-sheet
    prototype names a region kind and, after a dot, one of its source's
    variants. A sheet with regions has a kind tag: its prototypes' rows
    hold their kinds there."""
    if sheet.prototypes and not sheet.regions:
        raise DeclarationError(f"{at}.prototypes: a sheet's own prototypes are its regions' -- "
                               "name the regions")
    if not sheet.regions:
        return
    if sheet.role == "blocks":
        raise DeclarationError(f"{at}.regions: a blocks sheet fills from first_row; regions "
                               "are for flat, rates and display sheets")
    if sheet.tag("kind") is None:
        raise DeclarationError(f"{at}.tags: a sheet with regions needs a kind tag")
    ats = [r.at for r in sheet.regions]
    if ats != sorted(set(ats)):
        raise DeclarationError(f"{at}.regions: each at a later row than the one before")
    kinds = [k for r in sheet.regions for k in r.rows]
    if sheet.role == "flat":
        if sorted(kinds) != sorted(sheet.rows):
            raise DeclarationError(f"{at}.regions: list each of the sheet's rows once")
        for r in sheet.regions:
            if tuple(r.rows) not in display.FLAT:
                raise DeclarationError(f"{at}.regions: the fill lays out a flat region of "
                                       + " or ".join(", ".join(k) for k in display.FLAT))
    else:
        for kind in kinds:
            if kind not in display.SOURCES:
                raise DeclarationError(f"{at}.regions: {kind} is not a display source (known: "
                                       f"{', '.join(display.SOURCES)})")
        if len(kinds) != len(set(kinds)):
            raise DeclarationError(f"{at}.regions: list each source once")
    for key in sheet.prototypes:
        kind, _sep, variant = key.partition(".")
        if kind not in kinds:
            raise DeclarationError(f"{at}.prototypes.{key}: {kind} is in no region of this "
                                   "sheet")
        if variant and (sheet.role == "flat"
                        or variant not in display.SOURCES[kind].variants):
            raise DeclarationError(f"{at}.prototypes.{key}: {variant} is not a variant of "
                                   f"{kind}")


def _check_rates_labels(sheet, at):
    """A rates sheet the fill lays out writes what its reader reads
    (``reader.rates``): each rate row's id, name, unit and rate on the
    ``columns_by_key`` letters, a section's title in the id column and
    nothing else on a title row's read columns."""
    cols = sheet.columns_by_key
    rate = sheet.labels.get("RATE", {})
    for key in ("id", "name", "unit", "rate"):
        letter = cols[key]
        label = rate.get(letter)
        if label is None or label.path != key:
            raise DeclarationError(f"{at}.labels.RATE.{letter}: the reader reads the rate's "
                                   f"{key} in {letter} (columns_by_key.{key}) -- label it "
                                   f"{key}")
    title = sheet.labels.get("RATE_TITLE", {})
    read = {cols[k] for k in ("id", "name", "unit", "rate")}
    if (title.get(cols["id"]) is None or title[cols["id"]].path != "title"
            or any(letter in read for letter in title if letter != cols["id"])):
        raise DeclarationError(f"{at}.labels.RATE_TITLE: the reader reads a section's title in "
                               f"{cols['id']} (columns_by_key.id), with the other read "
                               "columns blank -- label it title there only")


def _showable(sheet) -> tuple:
    """The kinds ``sheet`` may name in ``not_shown``: the rows its owner
    block's kind holds (``contract.CHILDREN``) and the kinds nested under a
    container among its rows (``contract.UNDER``)."""
    found = [k for b in sheet.owner_blocks() for k in contract.CHILDREN.get(b.kind, ())]
    found += [k for c in sheet.rows for k in contract.UNDER.get(c, ())]
    return tuple(found)


def _check_not_shown(sheet, prototypes, at):
    """A kind left out on purpose (#439): one the coverage rules would ask
    for, appearing nowhere on the sheet, with no prototype -- top-level or
    the variant that carries its rows (``contract.VARIANTS``) -- the fill
    or an insert could place it from."""
    showable = _showable(sheet)
    kinds = sheet.kinds()
    for kind in sheet.not_shown:
        if kind not in showable:
            raise DeclarationError(f"{at}.not_shown: {kind} is not a kind this sheet holds "
                                   f"(it may leave out: {', '.join(showable) or 'nothing'})")
        forms = sheet.forms(kind)
        if any(f in kinds for f in forms) or any(
                f in getattr(sheet, section) for f in forms
                for section in ("fields", "export_values", "written", "labels")) or any(
                entry.partition(".")[0] in forms for entry in sheet.formulas):
            raise DeclarationError(f"{at}.not_shown: {kind} is shown on this sheet")
        owners = [b.kind for b in sheet.owner_blocks()]
        keys = [kind.lower()] + [v for o in owners
                                 for row, v in contract.VARIANTS.get(o, {}).items() if row == kind]
        for key in keys:
            if key in prototypes:
                raise DeclarationError(f"prototypes.{key}: {kind} is not shown on "
                                       f"sheets.{sheet.key} (not_shown)")


def _check_binding(sheet, kinds, kind, name, b, spec, at, tagged_rates):
    """A binding form's own rules (``Binding``)."""
    where = f"{at}.fields.{kind}.{name}"
    if b.rows is not None:
        if kinds.get(kind) != "owner":
            raise DeclarationError(f"{where}: a rows join binds an owner's field -- the rows "
                                   "sit in the owner's block")
        if b.rows in contract.TAGS:
            raise DeclarationError(f"{where}: {b.rows} is a contract kind; a joined row kind "
                                   "is the pack's own")
        if b.rows in sheet.markers:
            # ``kinds`` classes it joined either way; the marker would be
            # read as joined rows, unseen.
            raise DeclarationError(f"{at}.markers.{b.rows}: {b.rows} is a joined row kind "
                                   f"(fields.{kind}.{name}), not a marker")
        cls = kinds.get(b.rows)
        if cls != "joined":
            article = "an" if cls[0] in "aeiou" else "a"
            raise DeclarationError(f"{where}: {b.rows} is already {article} {cls} kind of "
                                   "this sheet")
        if b.column not in sheet.columns:
            raise DeclarationError(f"{where}: {b.column} is not a visible column")
    if (b.rows is not None or b.cells) and spec.reader not in ("text", "name"):
        raise DeclarationError(f"{where}: a join binds a text field")
    if b.from_rate is not None:
        if not tagged_rates:
            raise DeclarationError(f"{where}: from_rate needs a tagged rates sheet (one with a "
                                   "ref tag)")
        want = {"kind": "component_type", "rate": "unit_cost"}[b.from_rate]
        if name != want:
            raise DeclarationError(f"{where}: from_rate: {b.from_rate} binds {want}")
        named = sheet.binding(kind, "name")
        if named is None or named.column is None or named.rows is not None:
            raise DeclarationError(f"{where}: a row whose rate its name picks binds its name "
                                   "to a column")
    if b.by_name is not None and spec.reader != "number":
        raise DeclarationError(f"{where}: by_name binds a number")


def _check_spellings(sheet, at):
    """Spellings name a coded field some row of the sheet binds, and map to
    one of its choices."""
    for fname, table in sheet.spellings.items():
        specs = [contract.FIELDS[sheet.contract_kind(form)][fname]
                 for form, bound in sheet.fields.items() if fname in bound]
        if not specs:
            raise DeclarationError(f"{at}.spellings.{fname}: no row of this sheet binds {fname}")
        for spec in specs:
            choices = contract.CHOICES.get(spec.reader)
            if choices is None:
                raise DeclarationError(f"{at}.spellings.{fname}: {fname} is not a coded field")
            for text, value in table.items():
                if value not in choices:
                    raise DeclarationError(f"{at}.spellings.{fname}.{text}: {value!r} is not "
                                           f"one of {', '.join(choices)}")


def _check_sheet(sheet: Sheet, prototypes: dict, *, tagged_rates: bool = False) -> None:
    at = f"sheets.{sheet.key}"
    kinds = sheet.kinds()
    _check_not_shown(sheet, prototypes, at)
    tag_columns = {t.column for t in sheet.tags.values()}
    if sheet.role in ("blocks", "flat", "display") and sheet.tag("kind") is None:
        raise DeclarationError(f"{at}.tags: a {sheet.role} sheet needs a kind tag")
    # Display rows: read-model rows laid out as of export, never read back.
    if sheet.role == "display":
        if sheet.blocks or sheet.fields or sheet.markers or sheet.named_rows:
            raise DeclarationError(f"{at}: a display sheet lays out read-model rows only (no "
                                   "blocks, fields, markers or named rows)")
        if sheet.rows:
            raise DeclarationError(f"{at}.rows: a display sheet lists its kinds in regions")
        if not sheet.regions:
            raise DeclarationError(f"{at}: a display sheet names its regions")
    _check_regions(sheet, at)
    if sheet.each is not None:
        owner = next(iter(sheet.owner_blocks()), None)
        container = contract.CONTAINER.get(owner.kind) if owner else None
        if sheet.role != "blocks" or sheet.each != container or container not in sheet.rows:
            raise DeclarationError(f"{at}.each: a sheet repeats per row of its owner's "
                                   f"container ({container or 'none'}), listed in rows")
    # A container's nested kinds sit on its sheet (#439: a kind left out
    # would read every baseline row of it as missing).
    for container, nested in contract.UNDER.items():
        if container in sheet.rows:
            for kind in nested:
                if kind not in sheet.rows and kind not in sheet.not_shown:
                    raise DeclarationError(f"{at}.rows: a sheet with {container} rows lists "
                                           f"{kind} rows too, or names {kind} in not_shown")
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
        for name in contract.TAGS.get(sheet.contract_kind(kind), ()):
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
        tagged = sheet.tag("ref") is not None
        if sheet.local_suffix is not None and not tagged:
            raise DeclarationError(f"{at}.local_suffix: only a tagged rates sheet (one with a "
                                   "ref tag) has local rows")
        if tagged:
            if any(k not in sheet.columns_by_key for k in ("name", "kind", "rate")):
                raise DeclarationError(f"{at}.columns_by_key: a tagged rates sheet needs name, "
                                       "kind and rate")
            if sheet.tag("kind") is None:
                raise DeclarationError(f"{at}.tags: a tagged rates sheet needs a kind tag (its "
                                       f"library rows are tagged {contract.RATE_ROW})")
            if sheet.regions:
                raise DeclarationError(f"{at}.regions: a tagged rates sheet is not laid out by "
                                       "the fill (its reader is reader.rates.table)")
        elif any(k not in sheet.columns_by_key for k in ("id", "name", "unit", "rate")):
            raise DeclarationError(f"{at}.columns_by_key: a rates sheet needs id, name, unit "
                                   "and rate")
        for kind in sheet.sections:
            if kind not in contract.RATE_KINDS:
                raise DeclarationError(f"{at}.sections: {kind} is not a rate kind (known: "
                                       f"{', '.join(contract.RATE_KINDS)})")
        if not sheet.sections:
            raise DeclarationError(f"{at}.sections: a rates sheet needs at least one section")
        if sheet.regions:
            _check_rates_labels(sheet, at)
    # Fields: on a kind of this sheet, writable, once per kind, on a visible
    # column (never a tag column).
    for kind, bound in sheet.fields.items():
        if kind not in kinds:
            forms = sheet.forms(kind)
            if forms != (kind,):
                raise DeclarationError(f"{at}.fields.{kind}: {kind} rows are "
                                       f"{' and '.join(forms)} on this sheet -- bind each "
                                       "of them")
            raise DeclarationError(f"{at}.fields.{kind}: {kind} is not a row kind of this sheet")
        ck = sheet.contract_kind(kind)
        allowed = contract.FIELDS.get(ck)
        if allowed is None:
            raise DeclarationError(f"{at}.fields.{kind}: not a contract kind with writable fields")
        seen = {}
        for name, raw in bound.items():
            if name not in allowed:
                raise DeclarationError(f"{at}.fields.{kind}.{name}: not writable for {ck} "
                                       f"(writable: {', '.join(allowed)})")
            b = binding(raw)
            _check_binding(sheet, kinds, kind, name, b, allowed[name], at, tagged_rates)
            for letter in b.own_letters():
                if letter in tag_columns:
                    raise DeclarationError(f"{at}.fields.{kind}.{name}: {letter} is a tag column")
                if letter not in sheet.columns:
                    raise DeclarationError(f"{at}.fields.{kind}.{name}: {letter} is not a "
                                           "visible column")
                if letter in seen:
                    raise DeclarationError(f"{at}.fields.{kind}: column {letter} twice "
                                           f"({seen[letter]} and {name})")
                seen[letter] = name
    _check_spellings(sheet, at)
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
        # #439: a child kind left out would read every baseline row of it
        # as deleted.
        shown = {c.row for c in children}
        for kind in contract.CHILDREN.get(owner.kind, ()):
            if kind not in shown and kind not in sheet.not_shown:
                raise DeclarationError(f"{at}.blocks.{owner.name}: the {owner.kind} block needs "
                                       f"a child block for its {kind} rows -- one left out "
                                       "would read every baseline row of it as deleted; name "
                                       f"{kind} in not_shown to leave it out on purpose")
    for m in sheet.markers.values():
        if m.cue and m.cue[0] not in sheet.columns:
            raise DeclarationError(f"{at}.markers.{m.kind}.cue: column {m.cue[0]} is not visible")
    # Derived tags belong to block rows and markers, never to an owner kind.
    recursive = {b.kind for b in owner_blocks if b.recursive}
    for name, t in sheet.tags.items():
        for kind in t.derived:
            if kind in owners:
                # An owner whose block does not recurse has no parent to
                # store: its parent cell may hold the chain's formula.
                if name == "parent" and kind not in recursive:
                    continue
                opens = "a recursive block" if name == "parent" else "a block"
                raise DeclarationError(f"{at}.tags.{name}.derived: {kind} opens {opens}; its "
                                       f"{name} is stored, not derived")
            if not any(kinds.get(f) in ("child", "marker", "banner") for f in sheet.forms(kind)):
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
    # Labels: kinds of this sheet, read-model paths the kind has, never a
    # cell the row's fields or export values own, nor any tag column (a
    # tag another kind carries -- a step's ``parent`` -- is still the
    # sheet's: a label there overwrites it). The one exception is ``ref``
    # on a kind that stores none (``contract.REF_ATTR``): nothing writes or
    # reads it on that row (HeavyBook keeps an item's scope there). Header cells
    # sit above the rows and name the estimate, the export time or the host.
    for kind, bound in sheet.labels.items():
        if sheet.role in ("display", "rates"):
            # Its row kinds are its prototypes' (the lint checks the paths
            # against the rows' classes); no label sits on a tag column.
            for letter in bound:
                if letter in tag_columns:
                    raise DeclarationError(f"{at}.labels.{kind}.{letter}: {letter} is a tag "
                                           "column")
            continue
        if kind not in kinds:
            raise DeclarationError(f"{at}.labels.{kind}: {kind} is not a row kind of this sheet")
        owned = set(tag_columns)
        if sheet.contract_kind(kind) not in contract.REF_ATTR and sheet.tag("ref") is not None:
            owned.discard(sheet.tag("ref"))
        owned |= {letter for name in sheet.fields.get(kind, {})
                  for letter in sheet.binding(kind, name).own_letters()}
        owned |= set(sheet.export_values.get(kind, {}))
        for letter, label in bound.items():
            if letter in owned:
                raise DeclarationError(f"{at}.labels.{kind}.{letter}: {letter} holds a {kind} "
                                       "tag, field or export value")
            try:
                labels.check(sheet.contract_kind(kind), label)
            except labels.LabelError as exc:
                raise DeclarationError(f"{at}.labels.{kind}.{letter}: {exc}") from None
    # Header cells are written where the template has them: above every row
    # the fill places (the first region; first_row on a sheet without
    # regions), which no insert moves. A flat sheet's named rows sit above
    # its first region, from first_row on: a header cell may sit among them.
    for cell, label in sheet.header.items():
        row = int(cell.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        if not sheet.regions and row >= sheet.first_row:
            raise DeclarationError(f"{at}.header.{cell}: a header cell sits above first_row "
                                   f"({sheet.first_row})")
        if sheet.regions and row >= sheet.regions[0].at:
            raise DeclarationError(f"{at}.header.{cell}: a header cell sits above the first "
                                   f"region ({sheet.regions[0].at})")
        try:
            labels.check("header", label)
        except labels.LabelError as exc:
            raise DeclarationError(f"{at}.header.{cell}: {exc}") from None
    # Prototypes: every growable kind (an owner block's kind included, when
    # the contract lists it) unless its block is fixed. A growable kind
    # binds what a new row is created from (``contract.CREATE_NEEDS``: its
    # name; a step's duration, a line's type, a member's classification
    # and count): a create without one would be refused on every read.
    for b in sheet.blocks.values():
        if b.fixed:
            continue
        for kind in (b.kind, b.row):
            if kind not in contract.GROWABLE:
                continue
            # Each form is a row a book may grow: each has its prototype and
            # binds what a new row is created from.
            for form in sheet.forms(kind):
                if form.lower() not in prototypes:
                    raise DeclarationError(f"{at}.blocks.{b.name}: no prototype for {form} "
                                           f"(prototypes.{form.lower()}), and the block is "
                                           "not fixed")
                for need in contract.CREATE_NEEDS.get(kind, ()):
                    if need not in sheet.fields.get(form, {}):
                        raise DeclarationError(f"{at}.fields.{form}: a growable kind needs "
                                               f"its {need} bound")


def _check_aliases(aliases: dict, sheets: dict) -> None:
    """Each alias names a contract kind. An alias may take a contract
    kind's name (fieldbook's CREW, which is a crew in the contract): it
    shadows that kind, which the declaration then cannot show; so no sheet
    lists an aliased name among its flat rows (``sheets``: the document's),
    nor names one as a marker, a banner or a named row's kind -- places the
    loader does not resolve an alias, so the row would be read with the
    wrong tags. A contract kind with forms is shown by them, never under its
    own name among a sheet's rows."""
    shown = "an aliased kind is shown by its contract kind's blocks"
    for form, kind in aliases.items():
        if kind not in contract.TAGS:
            raise DeclarationError(f"kinds.{form}: {kind} is not a contract kind (known: "
                                   f"{', '.join(contract.TAGS)})")
        for key, raw in sheets.items():
            at = f"sheets.{key}"
            rows = raw.get("rows") or ()
            if form in rows:
                raise DeclarationError(f"kinds.{form}: {at}.rows lists {form} -- {shown}")
            if kind in rows:
                raise DeclarationError(f"kinds.{form}: {at}.rows lists {kind} -- a kind with "
                                       "forms is shown by its forms")
            if form in (raw.get("markers") or {}):
                raise DeclarationError(f"kinds.{form}: {at}.markers names {form} -- {shown}")
            for name, b in (raw.get("blocks") or {}).items():
                if b.get("banner") == form:
                    raise DeclarationError(f"kinds.{form}: {at}.blocks.{name}.banner names "
                                           f"{form} -- {shown}")
            for name, r in ((raw.get("named_rows") or {}).get("rows") or {}).items():
                if r.get("kind") == form:
                    raise DeclarationError(f"kinds.{form}: {at}.named_rows.rows.{name} names "
                                           f"{form} -- {shown}")


def _check_tab_or_each(doc: dict) -> None:
    """Each sheet names its ``tab`` or, repeating per container row, its
    ``each`` -- one of them (said before the schema, whose ``oneOf`` error
    names neither)."""
    sheets = doc.get("sheets")
    if not isinstance(sheets, dict):
        return
    for key, raw in sheets.items():
        if not isinstance(raw, dict):
            continue
        has = ("tab" in raw, "each" in raw)
        if all(has):
            raise DeclarationError(f"sheets.{key}: name a tab or each, not both")
        if not any(has):
            raise DeclarationError(f"sheets.{key}: name a tab or each")


def _check_each(sheets: dict) -> None:
    """One sheet repeats per container kind: a second would read every
    container's tab twice."""
    seen = {}
    for key, sheet in sheets.items():
        if sheet.each is None:
            continue
        if sheet.each in seen:
            raise DeclarationError(f"sheets.{key}.each: sheets.{seen[sheet.each]} already "
                                   f"repeats per {sheet.each}")
        seen[sheet.each] = key


def load(doc: dict) -> Declaration:
    """A ``Declaration`` from its document, or ``DeclarationError``."""
    if not isinstance(doc, dict):
        raise DeclarationError("the declaration is not an object")
    if doc.get("schema") != SCHEMA_VERSION:
        raise DeclarationError(f"schema {doc.get('schema')!r}: this reader knows schema "
                               f"{SCHEMA_VERSION}; update the plugin")
    _check_tab_or_each(doc)
    _validate(doc)
    aliases = dict(doc.get("kinds") or {})
    _check_aliases(aliases, doc["sheets"])
    prototypes = dict(doc.get("prototypes") or {})
    sheets = {key: _sheet(key, raw, aliases) for key, raw in doc["sheets"].items()}
    tagged_rates = any(s.role == "rates" and s.tag("ref") is not None for s in sheets.values())
    for sheet in sheets.values():
        _check_sheet(sheet, prototypes, tagged_rates=tagged_rates)
    _check_each(sheets)
    p = doc["pack"]
    return Declaration(schema=SCHEMA_VERSION, pack=PackId(p["name"], p["version"], p["contract"]),
                       kind=doc["kind"], sheets=sheets, prototypes=prototypes,
                       navigator=dict(doc.get("navigator") or {}), stamp=dict(doc.get("stamp") or {}),
                       aliases=aliases, raw=doc)


def lift_layout_map(layout_map: dict, *, pack: str, version: str, contract_major: str = "1",
                    into: dict | None = None) -> dict:
    """Fieldbook's ``layout_map:`` as a declaration document: the Navigator
    section is the map's tables and cells; the prototypes are the task row
    and the map's template rows under ``est.tpl.*`` (the rows
    ``FieldbookPack.templates`` names). Without ``into`` no sheet is
    declared; with it (fieldbook's ``pack.yaml``) the two sections are
    added to a copy of ``into``, which must not carry them itself.
    ``pack=``, ``version=`` and ``contract_major=`` are ignored when ``into``
    is given: the pack block is ``into``'s own."""
    templates = ((layout_map.get("templates") or {}).get("rows") or {})
    lifted = {"prototypes": {key: f"est.tpl.{key}" for key in ("task", *templates)},
              "navigator": {"tables": dict(layout_map.get("tables") or {}),
                            "cells": dict(layout_map.get("cells") or {}),
                            "tags": dict(layout_map.get("tags") or {}),
                            "blocks": dict(layout_map.get("blocks") or {})}}
    if into is None:
        return {"schema": SCHEMA_VERSION,
                "pack": {"name": pack, "version": version, "contract": contract_major},
                "kind": "recipe", "sheets": {}, **lifted}
    for key in lifted:
        if key in into:
            raise DeclarationError(f"{key}: lifted from the layout map -- the declaration "
                                   "must not carry it")
    return {**into, **lifted}
