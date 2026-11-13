"""The template lint (engine spec, Fill step 1): what a template pack's
``template.xlsx`` must hold for the fill to expand it, checked before
anything is written. Problems are the pack author's and name the sheet, the
cell and the formula; the fill refuses on any.

**Template.** Every sheet the declaration declares is a worksheet of the
template; so is the hidden stamp sheet ``_wb``. A ``blocks`` sheet holds
nothing from its ``first_row`` down: the fill owns those rows (a total over
them is written above the rows, over ``header_row`` to ``first_row``, which
every inserted row grows). A sheet with ``regions`` (a ``display`` sheet)
keeps each region's row blank -- the fill inserts above it, and it stays
under the rows it receives (a total over ``header:sentinel`` grows with
them) -- and its own rows around the regions (a heading between two, a
total below the last) move down with the inserts. Its tag columns are
hidden. A ``flat`` or ``rates`` sheet names its regions (without them the
fill places nothing on it); a flat sheet's named rows are the template's
own rows above its first region, each name once in the name column
(``Lint.named``), and the fill writes their values.

**Prototypes.** Each ``prototypes`` entry is a workbook-scoped defined name
over whole rows of one worksheet the declaration does not declare
(``_templates`` by convention); a name over a sheet the template lacks, or a
chart sheet, is refused by name. The fill needs, per blocks sheet, the owner's block (its
kind lower-cased: ``activity``) and each variant the contract names
(``contract.VARIANTS``: ``stepped``), one row per flat kind (``item``,
``element_qty``, ``group``) -- names no two blocks sheets may share -- and
every prototype a display sheet names in its own ``prototypes``, keyed by
its sheet (``shares:SHARE``): any rows, each with a kind; a row whose kind
is one of its source's children (``display.SOURCES``) is repeated per
child. A display prototype's labels resolve against its rows' classes, and
its id tag is blank (the fill writes it). A block prototype's rows
are its owner row, then each child block's open marker and one sample row,
then the last close marker -- exactly the declared order. Every prototype
row holds its kind in the kind tag (a blocks sheet's prototypes sit below
its ``header_row``, where the owner-row helper's rows-above form reads
neither its own cell nor row 0); its stored tags, bound inputs, export
values and labels are blank; its derived tags hold formulas; its owner-row
cell is blank or the engine's own formula; its written text is the
declaration's.

**Prototype formulas.** A formula may read its own row; inside a block
prototype, an owner or marker row may also read the block's owner and
marker rows (the brackets its sums span), never a sample row (a sample is
copied once per payload row); a defined name; a whole column; a cell or range of
a sheet the fill does not expand (a rates or markup sheet) whose rows are
absolute (``Markup!B$2``: a copied row moves a relative row of any sheet,
so ``Markup!B2`` placed 23 rows down reads ``Markup!B25``); a whole column
or a defined name of a sheet it does. It may read the rows above its own as
``X$<start>:X<row above>`` (the engine's own owner-row form, which an
inserted row grows), ``start`` its sheet's ``header_row`` -- on a sheet with
regions, the row above the prototype's region, or the ``header_row`` when
that is above the region -- and above the prototype row. It may not read a
fixed row of an expanded sheet -- the reference that breaks when a row is
inserted -- nor the prototype
sheet, another workbook or a 3-D span, and may not call ``INDIRECT`` or
``OFFSET``, which the lint cannot follow.

**Package.** The fill writes through ``exchange.writer``, which keeps every
part of the template (charts, images, VBA, extension validations) and moves
every reference an inserted row moves. What it does not copy from a
prototype row onto the rows it places -- merged cells, conditional formats,
notes, hyperlinks and Excel 2010 extension validations on a prototype row
-- is listed in ``Lint.dropped``; the fill refuses unless the author passes
``allow_dropped`` (``--allow-dropped``), and the build report lists it."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter

from estimating_tools.exchange import contract, display, labels, refs
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange import writer as W
from estimating_tools.exchange.reader.blocks import Blocks
from estimating_tools.exchange.reader.fields import inputs_for_decl

__all__ = ["FILLED", "Lint", "LintError", "Proto", "check", "is_stepped", "needed",
           "owner_row_formula"]

#: The sheet roles a fill expands.
FILLED = ("blocks", "display", "flat", "rates")
#: Functions whose references the lint cannot follow.
OPAQUE = ("INDIRECT", "OFFSET")
X14 = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"


class LintError(ValueError):
    """The template cannot be filled; ``problems`` lists every reason."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class Proto:
    """A prototype: its key, its sheet, its rows and each row's kind."""
    key: str
    sheet: str
    first: int
    last: int
    kinds: tuple


@dataclass
class Lint:
    protos: dict = field(default_factory=dict)       # key -> Proto
    problems: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    named: dict = field(default_factory=dict)        # sheet key -> {name: template row}
    #: workbook-scoped name -> (sheet, first column, first row, last column,
    #: last row): the template's names over a range of one sheet
    #: (``fill.prepare`` fits those that end on a fill region's row).
    ranges: dict = field(default_factory=dict)

    @property
    def sheet(self) -> str | None:
        """The prototype sheet (every prototype sits on one)."""
        return next((p.sheet for p in self.protos.values()), None)


def owner_row_formula(kind_col: str, owner: str, col: str, header: int, row: int) -> str:
    """The engine's owner-row helper at ``row`` (engine spec, Fill step 3):
    this row when it is an ``owner`` row, else the largest helper above --
    HeavyBook's ``formulas.activity_row``, for any pack."""
    return (f'=IF({kind_col}{row}="{owner}",ROW(),'
            f"MAX({col}${header}:{col}{row - 1}))")


def _prototype_names(wb) -> dict:
    """Workbook-scoped defined name -> (sheet, first row, last row), for
    names over whole rows of one sheet."""
    out = {}
    for name, dn in wb.defined_names.items():
        dests = list(dn.destinations)
        if len(dests) != 1:
            continue
        sheet, ref = dests[0]
        first, sep, last = ref.replace("$", "").partition(":")
        if first.isdigit() and (not sep or last.isdigit()):
            out[name] = (sheet, int(first), int(last or first))
    return out


_RANGE = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?$")


def _ranges(wb) -> dict:
    """Workbook-scoped defined name -> (sheet, first column, first row, last
    column, last row), for names over one cell range of one sheet."""
    out = {}
    for name, dn in wb.defined_names.items():
        dests = list(dn.destinations)
        if len(dests) != 1:
            continue
        sheet, ref = dests[0]
        m = _RANGE.match(ref)
        if m:
            c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            out[name] = (sheet, c1, r1, c2 or c1, int(r2) if r2 else r1)
    return out


def _hidden(ws) -> set:
    """The letters of the columns ``ws`` hides."""
    out = set()
    for dim in ws.column_dimensions.values():
        if dim.hidden and dim.min and dim.max:
            out |= {get_column_letter(n) for n in range(dim.min, dim.max + 1)}
    return out


def _value(ws, letter, row):
    return ws[f"{letter}{row}"].value


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


def _expected(sheet, key) -> tuple:
    """The kinds of block prototype ``key``'s rows, top to bottom: the owner,
    then each child's open marker (unless the owner row or the previous
    child's close opens it) and one sample row, then the last close marker.
    A variant includes the row it names -- ``stepped`` its optional STEP
    block, ``library`` the members' NOTE banner, after the open marker --
    the plain prototype leaves every optional child and banner out."""
    b = Blocks(sheet)
    owner = b.owner.kind
    with_rows = {row for row, variant in contract.VARIANTS.get(owner, {}).items()
                 if variant == key}
    seq = [owner]
    for child in b.children:
        if child.optional and child.row not in with_rows:
            continue
        if child.open != owner and seq[-1] != child.open:
            seq.append(child.open)
        if child.banner and child.banner in with_rows:
            seq.append(child.banner)
        seq.append(child.row)
    seq.append(b.last.close)
    return tuple(seq)


def needed(decl) -> dict:
    """``{prototype key: (sheet key, the kinds of its rows)}``: the prototypes
    the fill copies, per sheet it expands."""
    out = {}
    for key, sheet in decl.sheets.items():
        if sheet.role not in FILLED:
            continue
        # Fill-only prototypes: a display (flat, rates) sheet's own, keyed by
        # its sheet; their rows' kinds are what the template holds
        # (``_protos`` reads them).
        for proto_key in sheet.prototypes:
            out[f"{key}:{proto_key}"] = (key, None)
        if sheet.role == "blocks":
            for kind in sheet.rows:
                out[kind.lower()] = (key, (kind,))
            b = Blocks(sheet)
            owner = b.owner.kind
            out[owner.lower()] = (key, _expected(sheet, owner.lower()))
            # A variant only where its child block is optional, or for a
            # banner (a library crew's NOTE): a required child is in the
            # plain prototype already (``_expected``).
            optional = {c.row for c in b.children if c.optional}
            optional |= {c.banner for c in b.children if c.banner}
            for row, variant in contract.VARIANTS.get(owner, {}).items():
                if row in optional:
                    out[variant] = (key, _expected(sheet, variant))
            for child in b.children:
                if child.row in contract.GROWABLE and not child.fixed:
                    out.setdefault(child.row.lower(), (key, (child.row,)))
    return out


def is_stepped(kinds) -> bool:
    """A block prototype whose rows (``kinds``, owner first) include the
    STEP block (``contract.VARIANTS``: ``stepped``; a crew's banner steps
    nothing) -- a stepped activity, as the reader reads one
    (``Occurrence.has_steps_marker``): its stepless-only inputs are not
    inputs and its ``ACTIVITY.stepped`` formulas are. Decided by the rows, not the prototype's key: with a
    required STEP block the plain ``activity`` prototype is stepped."""
    return bool(kinds) and contract.VARIANTS.get(kinds[0], {}).get("STEP") == "stepped" \
        and "STEP" in kinds


def _stored(sheet, kind) -> list:
    """The tag letters ``kind`` stores (values the fill writes): its
    identity tags that are not derived for it."""
    out = []
    names = contract.tags_for(kind, marker=sheet.kinds().get(kind) in ("marker", "banner"))
    for name in names:
        tag = sheet.tags.get(name)
        if tag is not None and kind not in tag.derived:
            out.append(tag.column)
    return out


def _derived(sheet, kind) -> list:
    return [t.column for t in sheet.tags.values() if kind in t.derived]


class _Checker:
    def __init__(self, decl, wb, lint):
        self.decl, self.wb, self.lint = decl, wb, lint
        self.filled = {s.tab: s for s in decl.sheets.values() if s.role in FILLED}

    def problem(self, text):
        self.lint.problems.append(text)

    # -- cells -------------------------------------------------------------

    def cells(self, proto, sheet_key):
        sheet = self.decl.sheets[sheet_key]
        ws = self.wb[proto.sheet]
        stepped = is_stepped(proto.kinds)
        owner_col = sheet.tag("owner_row")
        shown = sheet.role in ("display", "rates")
        starts = _starts(sheet, proto)
        for offset, kind in enumerate(proto.kinds):
            r = proto.first + offset
            where = f"{proto.sheet} row {r} ({kind.lower()} prototype {proto.key})"
            for letter in () if shown else _stored(sheet, kind):
                if not _blank(_value(ws, letter, r)):
                    self.problem(f"{where}: {letter} is a stored tag -- leave it blank, the fill "
                                 "writes it")
            if shown and sheet.tag("id") and not _blank(_value(ws, sheet.tag("id"), r)):
                self.problem(f"{where}: {sheet.tag('id')} is the id tag -- leave it blank, the "
                             "fill writes it")
            for letter in _derived(sheet, kind):
                if not _is_formula(_value(ws, letter, r)):
                    self.problem(f"{where}: {letter} is a derived tag -- it needs its chain "
                                 "formula")
            for inp in () if shown else inputs_for_decl(self.decl, sheet_key, kind,
                                                        stepped=stepped):
                if not _blank(_value(ws, inp.letter, r)):
                    self.problem(f"{where}: {inp.letter} is the {inp.field} input -- leave it "
                                 "blank, the fill writes it")
            for letter in (*sheet.export_values.get(kind, {}), *sheet.labels.get(kind, {})):
                if not _blank(_value(ws, letter, r)):
                    self.problem(f"{where}: {letter} is an export value or label -- leave it "
                                 "blank, the fill writes it")
            for letter, text in sheet.written.get(kind, {}).items():
                if _value(ws, letter, r) != text:
                    self.problem(f"{where}: {letter} must hold the written text {text!r}")
            # The fill writes the owner-row helper on every prototype row
            # (``values.prototype_cells``) and the writer never overwrites a
            # formula: the cell stays blank, even of the helper's own form.
            if owner_col is not None and not _blank(_value(ws, owner_col, r)):
                self.problem(f"{where}: {owner_col} is the owner-row helper the engine "
                             "writes -- leave it blank")
            self.formulas(ws, proto, offset, sheet, skip={owner_col}, starts=starts)

    # -- formulas ----------------------------------------------------------

    def formulas(self, ws, proto, offset, sheet, skip, starts):
        r = proto.first + offset
        kinds = sheet.kinds()
        owner_or_marker = {proto.first + i for i, k in enumerate(proto.kinds)
                           if kinds.get(k) in ("owner", "marker")}
        mine = kinds.get(proto.kinds[offset]) in ("owner", "marker") and len(proto.kinds) > 1
        for cell in ws[r]:
            if isinstance(cell, MergedCell) or cell.column_letter in skip \
                    or not _is_formula(cell.value):
                continue
            where = f"{proto.sheet}!{cell.coordinate}: {cell.value}"
            try:
                found = refs.references(cell.value[1:])
                called = refs.functions(cell.value[1:])
            except refs.RefsError as exc:
                self.problem(f"{where}: {exc}")
                continue
            for name in sorted(called & set(OPAQUE)):
                self.problem(f"{where}: {name} -- the lint cannot follow what it reads; use "
                             "INDEX over a whole column")
            for ref in found:
                why = self.why_not(ref, r, mine, owner_or_marker, starts)
                if why:
                    self.problem(f"{where}: {ref.text} {why}")

    def why_not(self, ref, r, mine, block_rows, starts):
        if ref.external:
            return "reads another workbook"
        if ref.three_d:
            return "is a 3-D reference"
        if ref.sheet is not None:
            if ref.sheet.casefold() in {n.casefold() for n in self.lint_sheets()}:
                return "reads the prototype sheet -- a copied row would keep reading it"
            target = next((s for tab, s in self.filled.items()
                           if tab.casefold() == ref.sheet.casefold()), None)
            if target is not None and ref.shape not in ("columns", "name"):
                return ("is a fixed row of a sheet the fill expands -- read a whole column "
                        "(INDEX/MATCH) or a defined name")
            if any(not absolute for _row, absolute in ref.rows):
                # A copied row moves every relative row, of any sheet.
                return ("is a relative row of a sheet the fill does not expand -- a copied "
                        "row would read another row; anchor the row with $")
            return None
        if ref.shape in ("columns", "name"):
            return None
        rows = ref.rows
        if (ref.shape == "area" and len(rows) == 2 and rows[0][1] and rows[0][0] in starts
                and rows[1] == (r - 1, False)):
            if rows[0][0] < r:
                return None                               # the rows above: X$4:X<r-1>
            return (f"starts at row {rows[0][0]}, at or below this prototype's row {r} -- put "
                    f"the prototype below row {rows[0][0]} on its sheet")
        for row, absolute in rows:
            if absolute:
                return "is a fixed row of a sheet the fill expands -- the reference an " \
                       "inserted row breaks"
            if row == r:
                continue
            if mine and row in block_rows:
                continue
            return ("reads another row -- a prototype row reads its own row"
                    + (", and its block's owner and marker rows" if mine else ""))
        return None

    def lint_sheets(self):
        return {p.sheet for p in self.lint.protos.values()}


def _package(path, wb, lint):
    """What the fill does not copy from a prototype row: merged cells,
    conditional formats, notes, hyperlinks, extension validations."""
    rows_of = {}
    for p in lint.protos.values():
        rows_of.setdefault(p.sheet, set()).update(range(p.first, p.last + 1))

    def touches(sqref, rows):
        for part in (sqref or "").split():
            got = refs.span(part.replace("$", ""))
            if got and any(got[0] <= r <= got[1] for r in rows):
                return part
        return None

    for title, rows in rows_of.items():
        ws = wb[title]
        for rng in ws.merged_cells.ranges:
            if touches(str(rng), rows):
                lint.dropped.append(f"{title}!{rng}: merged cells on a prototype row")
        for cf in ws.conditional_formatting:
            hit = touches(str(cf.sqref), rows)
            if hit:
                lint.dropped.append(f"{title}!{hit}: a conditional format on a prototype row")
        for row in ws.iter_rows(min_row=min(rows), max_row=max(rows)):
            for cell in row:
                if isinstance(cell, MergedCell) or cell.row not in rows:
                    continue
                if cell.comment is not None:
                    lint.dropped.append(f"{title}!{cell.coordinate}: a note on a prototype row")
                if cell.hyperlink is not None:
                    lint.dropped.append(f"{title}!{cell.coordinate}: a hyperlink on a "
                                        "prototype row")
    with zipfile.ZipFile(path) as z:
        parts = W._sheet_parts(z)
        for title, rows in rows_of.items():
            root = ET.fromstring(z.read(parts[title]))
            for el in root.iter():
                if el.tag in (f"{{{X14}}}dataValidation", f"{{{X14}}}conditionalFormatting"):
                    sq = el.find("{http://schemas.microsoft.com/office/excel/2006/main}sqref")
                    hit = touches(sq.text if sq is not None else "", rows)
                    if hit:
                        what = ("an Excel 2010 validation" if el.tag.endswith("dataValidation")
                                else "an Excel 2010 conditional format")
                        lint.dropped.append(f"{title}!{hit}: {what} on a prototype row")


def check(path, decl) -> Lint:
    """Lint the template at ``path`` against ``decl`` (a loaded
    ``Declaration``). Returns the ``Lint`` (its ``protos`` resolved);
    ``LintError`` when there is any problem."""
    from openpyxl import load_workbook

    lint = Lint()
    path = Path(path)
    try:
        wb = load_workbook(path, data_only=False)
    except Exception as exc:  # noqa: BLE001 -- any unreadable template is one problem
        raise LintError([f"{path.name}: cannot read the template as an .xlsx workbook "
                         f"({exc})"]) from None
    try:
        _sheets(decl, wb, lint)
        lint.ranges = _ranges(wb)
        _protos(decl, wb, lint)
        _navigator(decl, wb, lint)
        _named_rows(decl, wb, lint)
        _shared_keys(decl, lint)
        if not lint.problems:
            _display_labels(decl, lint)
            checker = _Checker(decl, wb, lint)
            for key, (sheet_key, _kinds) in needed(decl).items():
                checker.cells(lint.protos[key], sheet_key)
            _package(path, wb, lint)
    finally:
        wb.close()
    if lint.problems:
        raise LintError(lint.problems)
    return lint


def _sheets(decl, wb, lint):
    names = set(wb.sheetnames)
    if exchange_stamp.SHEET not in names:
        lint.problems.append(f"the template has no {exchange_stamp.SHEET} sheet -- add a hidden "
                             f"worksheet named {exchange_stamp.SHEET} (the fill writes the stamp "
                             "there)")
    elif wb[exchange_stamp.SHEET].sheet_state == "visible":
        lint.problems.append(f"the {exchange_stamp.SHEET} sheet must be hidden")
    for key, sheet in decl.sheets.items():
        if sheet.tab not in names:
            lint.problems.append(f"sheets.{key}: the template has no sheet {sheet.tab!r}")
            continue
        if sheet.role in ("flat", "rates") and not sheet.regions:
            # Without regions ``fill.plan.regions`` places nothing on it.
            lint.problems.append(f"sheets.{key}: a {sheet.role} sheet the fill lays out names "
                                 "its regions")
            continue
        ws = wb[sheet.tab]
        for cell in sheet.header:
            if not _blank(ws[cell].value):
                lint.problems.append(f"{sheet.tab}!{cell}: a header cell the fill writes -- "
                                     "leave it blank")
        if sheet.role == "blocks" and sheet.tag("owner_row") and (
                sheet.header_row is None or sheet.header_row >= sheet.first_row):
            lint.problems.append(f"sheets.{key}: an owner-row helper needs a header_row above "
                                 "first_row")
        if sheet.regions:
            # Each region's row is the one the fill inserts above: it stays,
            # blank, under the rows it receives. The template's own rows
            # around the regions are the author's and move down with them.
            for region in sheet.regions:
                taken = next((c for c in ws[region.at] if not _blank(c.value)), None)
                if taken is not None:
                    lint.problems.append(f"{sheet.tab}!{taken.coordinate}: the fill inserts "
                                         "above this row -- leave the row blank")
        else:
            for row in ws.iter_rows(min_row=sheet.first_row):
                taken = next((c for c in row if not _blank(c.value)), None)
                if taken is not None:
                    lint.problems.append(f"{sheet.tab}!{taken.coordinate}: the fill owns the "
                                         f"rows from {sheet.first_row} down -- move this above "
                                         "the header, or delete it")
                    break
        hidden = _hidden(ws) if ws.sheet_state == "visible" else None
        for name, tag in sorted(sheet.tags.items()) if hidden is not None else ():
            if tag.column not in hidden:
                lint.problems.append(f"{sheet.tab} column {tag.column} holds the {name} tag "
                                     "and must be hidden")


def _protos(decl, wb, lint):
    names = _prototype_names(wb)
    declared = {s.tab for s in decl.sheets.values()} | {exchange_stamp.SHEET}
    for key, (sheet_key, kinds) in needed(decl).items():
        own = key.partition(":")[2] if ":" in key else None
        name = (decl.sheets[sheet_key].prototypes.get(own) if own is not None
                else decl.prototypes.get(key))
        where = f"sheets.{sheet_key}.prototypes.{own}" if own is not None else f"prototypes.{key}"
        if name is None:
            lint.problems.append(f"{where}: the fill needs a {key} prototype "
                                 f"(sheets.{sheet_key})")
            continue
        got = names.get(name)
        if got is None:
            lint.problems.append(f"{where}: no defined name {name} over whole rows "
                                 "in the template")
            continue
        title, first, last = got
        target = f"'{title}'!${first}:${last}"
        if title in declared:
            lint.problems.append(f"{where}: {name} is on {title}, a sheet the pack "
                                 "declares -- prototypes sit on their own sheet")
            continue
        # A name may point anywhere: at a sheet the template lacks, or at a
        # chart sheet (no cells). Neither holds a row to copy.
        if title not in wb.sheetnames:
            lint.problems.append(f"{where}: {name} ({target}) is on a sheet the "
                                 "template does not have")
            continue
        if title not in {w.title for w in wb.worksheets}:
            lint.problems.append(f"{where}: {name} ({target}) is on a chart sheet -- "
                                 "prototypes are rows of a worksheet")
            continue
        sheet = decl.sheets[sheet_key]
        ws = wb[title]
        found = tuple(str(_value(ws, sheet.tag("kind"), r) or "").strip()
                      for r in range(first, last + 1))
        if kinds is None:                     # a fill-only prototype: any rows with kinds
            kinds = found
            if "" in kinds:
                lint.problems.append(f"{where}: {name} ({title} rows {first}-{last}) has a "
                                     "row without a kind in the sheet's kind column "
                                     f"{sheet.tag('kind')}")
                continue
        if found != kinds:
            lint.problems.append(f"{where}: {name} ({title} rows {first}-{last}) holds "
                                 f"{', '.join(k or '(blank)' for k in found)} in its kind "
                                 f"column; the fill needs {', '.join(kinds)}")
            continue
        # The owner-row helper on a prototype row reads the rows above it
        # from the header row (``MAX(M$<header>:M<r-1>)``, which a patch or
        # refresh insert translates to its own row): a prototype at or above
        # the header would read its own cell, or row 0.
        header = sheet.header_row
        if sheet.role == "blocks" and sheet.tag("owner_row") and header is not None \
                and first <= header:
            lint.problems.append(f"{where}: {name} ({title} rows {first}-{last}) starts "
                                 f"at or above {sheet.tab}'s header row {header} -- the "
                                 "owner-row helper reads the rows above from there; put the "
                                 f"prototype below row {header}")
            continue
        lint.protos[key] = Proto(key, title, first, last, kinds)
    sheets = sorted({p.sheet for p in lint.protos.values()})
    if len(sheets) > 1:
        lint.problems.append(f"prototypes: every prototype sits on one sheet (found "
                             f"{', '.join(sheets)})")


def _navigator(decl, wb, lint):
    """The defined names the declaration's ``navigator`` section names (the
    add-in finds a book's tables, cells and insert templates by them) are
    the template's own: an author defines them in Excel, and the fill's
    inserts move them with the rows."""
    nav = decl.navigator or {}
    wanted = [(f"navigator.templates.{k}", n) for k, n in (nav.get("templates") or {}).items()]
    wanted += [(f"navigator.cells.{k}", n) for k, n in (nav.get("cells") or {}).items()]
    wanted += [(f"navigator.tables.{k}", (t or {}).get("name"))
               for k, t in (nav.get("tables") or {}).items()]
    for where, name in wanted:
        if name and name not in wb.defined_names:
            lint.problems.append(f"{where}: no defined name {name} in the template")


def _named_rows(decl, wb, lint):
    """A flat sheet's named rows are the template's own rows above its first
    region, found by their name in the name column; each declared name is
    there once."""
    for key, sheet in decl.sheets.items():
        if not sheet.named_rows or sheet.tab not in wb.sheetnames:
            continue
        ws = wb[sheet.tab]
        top = sheet.regions[0].at if sheet.regions else ws.max_row + 1
        found = {}
        for r in range(1, top):
            name = _value(ws, sheet.named_rows.name_column, r)
            if isinstance(name, str) and name.strip() in sheet.named_rows.rows:
                found.setdefault(name.strip(), []).append(r)
        for name in sheet.named_rows.rows:
            rows = found.get(name, [])
            if len(rows) != 1:
                lint.problems.append(f"sheets.{key}.named_rows.{name}: the template holds it "
                                     f"{len(rows)} times above row {top} (in "
                                     f"{sheet.named_rows.name_column}); it needs it once")
        lint.named[key] = {name: rows[0] for name, rows in found.items() if len(rows) == 1}


def _shared_keys(decl, lint):
    """A blocks sheet's prototypes are named by kind (``activity``,
    ``item``), the names patch, refresh and the Navigator insert by: two
    blocks sheets that need the same one cannot both have it."""
    seen = {}
    for key, sheet in decl.sheets.items():
        if sheet.role != "blocks":
            continue
        mine = set(_needed_by(decl, key))
        for proto_key in sorted(mine):
            if proto_key in seen:
                lint.problems.append(f"prototypes.{proto_key}: sheets.{seen[proto_key]} and "
                                     f"sheets.{key} both need the {proto_key} prototype -- lay "
                                     "one of them out on a display sheet, whose prototypes "
                                     "are its own")
            else:
                seen[proto_key] = key


def _needed_by(decl, key) -> dict:
    """``needed`` for one sheet (``needed`` keeps the last sheet's on a
    shared name)."""
    from dataclasses import replace

    return needed(replace(decl, sheets={key: decl.sheets[key]}))


def _region_of(sheet, proto):
    """The region a sheet's own prototype lays its rows out in."""
    kind = proto.key.partition(":")[2].partition(".")[0]
    return next((r for r in sheet.regions if kind in r.rows), None)


def _starts(sheet, proto) -> set:
    """The rows a prototype formula's rows-above form may start at: the
    sheet's ``header_row``, or -- on a sheet with regions -- the row above
    the prototype's region, or the ``header_row`` when it is above it with
    no other region between (a later region never reads an earlier one's
    rows)."""
    header = sheet.header_row
    if not sheet.regions:
        return {header} if header is not None else set()
    region = _region_of(sheet, proto)
    if region is None:
        return set()
    out = {region.at - 1} if region.at > 1 else set()
    if header is not None and header < region.at and not any(
            header < other.at < region.at for other in sheet.regions):
        out.add(header)
    return out


def _row_classes(decl, key, lint) -> dict:
    """``{row kind: read-model class}`` for a display or rates sheet's
    prototype rows: a source's child kind its child's class, every other
    row its source's. A row kind two prototypes hold as rows of different
    classes is a problem: its labels could not resolve on both."""
    sheet = decl.sheets[key]
    out = {}
    for proto_key in sheet.prototypes:
        proto = lint.protos.get(f"{key}:{proto_key}")
        if proto is None:
            continue
        src = display.SOURCES[proto_key.partition(".")[0]]
        for kind in proto.kinds:
            cls = src.children[kind][0] if kind in src.children else src.cls
            if out.setdefault(kind, cls) is not cls:
                lint.problems.append(f"sheets.{key}.prototypes.{proto_key}: its {kind} rows show "
                                     f"{cls.__name__} objects; another prototype's show "
                                     f"{out[kind].__name__} -- give them different kinds")
    return out


def _display_labels(decl, lint):
    """A display or rates sheet's labels name kinds its prototypes hold, and
    paths those rows' classes have."""
    for key, sheet in decl.sheets.items():
        if sheet.role not in ("display", "rates") or not sheet.prototypes:
            continue
        classes = _row_classes(decl, key, lint)
        for kind, bound in sorted(sheet.labels.items()):
            if kind not in classes:
                lint.problems.append(f"sheets.{key}.labels.{kind}: no prototype of this sheet "
                                     f"has {kind} rows")
                continue
            for letter, label in sorted(bound.items()):
                try:
                    labels.check_path(classes[kind], label.path)
                except labels.LabelError as exc:
                    lint.problems.append(f"sheets.{key}.labels.{kind}.{letter}: {exc}")
