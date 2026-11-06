"""Whole-row inserts and deletes inside an .xlsx package, the way Excel makes
them, for the patch writer (engine spec, "Patch and refresh": the writer
"inserts rows by copying a prototype's rows and shifting the references the
insertion moves"). The workbook is never loaded through openpyxl: each part
an op touches is edited as XML and re-serialised with
``writer._serialize_like``; every other part is copied byte for byte by
``writer.edit``.

An op is :class:`InsertRows` (copies of prototype rows from another sheet,
placed above a row) or :class:`DeleteRows`. Ops apply in the order given,
each in the coordinates the ops before it left; :class:`RowMap` says where a
row ended up. A caller that sorts its ops bottom-up per sheet can name every
op by the book's original row numbers.

What moves with the rows (Excel's rules, mirrored by the test suite's
``simulate_insert_copied_row`` and ``simulate_delete_row``):

- every formula reference into the edited sheet, on every sheet
  (``exchange.refs``), shared formulas expanded first where a group touches
  it; defined names; chart series (``c:f``);
- on the edited sheet: cell and row numbers, merged ranges, conditional
  formats and data validations (ranges, formulas and formula thresholds,
  the x14 extension ones included; a formula is re-anchored when its
  range's first cell is deleted), hyperlinks, row breaks, the dimension
  (grown to hold copied rows), tables and the auto filter, ignored errors,
  protected ranges and sort ranges (an emptied one is removed), notes
  (comments, their VML shapes, threaded comments) and drawing anchors;
- the view (pane, selection) stays where it was, as Excel leaves it;
- the calculation chain is dropped (Excel rebuilds it); ``writer.edit`` asks
  for a full calculation on open.

An inserted row takes its prototype row's cells (values, shared-string
indexes, styles, formulas translated to the new row as Excel's copy
translates them) and row attributes, minus ``skip`` columns, and the
prototype sheet's sheet-level data validations, their formulas moved as
Excel's copy moves them (merged into an equivalent validation of the target
sheet when there is one).

Refused with nothing written (``RowOpError``): a merged range, table, auto
filter or array formula the boundary would cut; a pivot table on the edited
sheet or reading it; a data table; a 3-D reference whose span includes the
edited sheet; rows that would run past Excel's last row; a deleted row
holding a note, a hyperlink or a drawing's anchor; a conditional format or
data validation reading another row (or another sheet) relatively when the
op lands inside its range (Excel splits such a rule in two; the writer does
not); a defined name, conditional format, data validation or chart series
that would lose its reference; and a cell formula that would lose its
reference on a sheet not in ``lost_ok`` (one on a sheet in ``lost_ok`` reads
``#REF!``, as Excel's own delete leaves it, and is returned in
``Outcome.lost`` where the later ops left it). A refusal names the sheet and
the cell, rule or object."""
from __future__ import annotations

import copy
import posixpath
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter

from estimating_tools.exchange import refs
from estimating_tools.exchange import writer as W

__all__ = ["DeleteRows", "InsertRows", "Outcome", "RowMap", "RowOpError", "apply"]


class RowOpError(ValueError):
    """A row op the writer will not make; nothing is written. The message
    names the sheet and the cell or object in the way."""


@dataclass(frozen=True)
class InsertRows:
    """Insert ``times`` copies of rows ``first..last`` of sheet ``source`` (a
    prototype sheet) above row ``before`` of ``sheet``: the copies take rows
    ``before`` onwards and every row from ``before`` down moves by
    ``count``. Columns in ``skip`` (letters) are not copied."""
    sheet: str
    before: int
    source: str
    first: int
    last: int
    times: int = 1
    skip: tuple = ()

    def __post_init__(self):
        if self.before < 1 or self.first < 1 or self.last < self.first or self.times < 1:
            raise ValueError(f"InsertRows({self.sheet!r}, before={self.before}, rows "
                             f"{self.first}-{self.last}, times={self.times}): not a row range")
        if self.source == self.sheet:
            raise ValueError("InsertRows copies prototype rows from another sheet")
        if self.last > refs.MAX_ROW or self.before > refs.MAX_ROW:
            raise ValueError(f"InsertRows({self.sheet!r}, before={self.before}, rows "
                             f"{self.first}-{self.last}): past Excel's last row")

    @property
    def width(self) -> int:
        return self.last - self.first + 1

    @property
    def count(self) -> int:
        return self.width * self.times

    def move(self):
        return refs.Insert(self.before, self.count)


@dataclass(frozen=True)
class DeleteRows:
    """Delete rows ``first..first+count-1`` of ``sheet``."""
    sheet: str
    first: int
    count: int = 1

    def __post_init__(self):
        if self.first < 1 or self.count < 1:
            raise ValueError(f"DeleteRows({self.sheet!r}, first={self.first}, "
                             f"count={self.count}): not a row range")

    @property
    def last(self) -> int:
        return self.first + self.count - 1

    def move(self):
        return refs.Delete(self.first, self.count)


class RowMap:
    """Where rows end up after ``ops`` (applied in order, each in the
    coordinates the ones before it left)."""

    def __init__(self, ops):
        self.ops = list(ops)

    def _through(self, sheet, row, start):
        for op in self.ops[start:]:
            if op.sheet != sheet:
                continue
            got = op.move().rows(row, row)
            if got is None:
                return None
            row = got[0]
        return row

    def row(self, sheet: str, row: int):
        """Where row ``row`` of ``sheet`` (as it was before every op) ends up;
        None when an op deleted it."""
        return self._through(sheet, row, 0)

    def inserted(self, index: int) -> list:
        """The final rows of op ``index``'s inserted rows, in order."""
        op = self.ops[index]
        if not isinstance(op, InsertRows):
            raise ValueError(f"op {index} inserts no rows")
        return [self._through(op.sheet, op.before + k, index + 1) for k in range(op.count)]


@dataclass
class Outcome:
    """What ``apply`` made: ``replacements`` (part name -> bytes, or None for
    a part removed) and ``lost`` (``(sheet, cell, formula)`` for each cell
    formula on a ``lost_ok`` sheet that now reads ``#REF!``)."""
    replacements: dict = field(default_factory=dict)
    lost: list = field(default_factory=list)


NS, NS_REL = W.NS, W.NS_REL
XM = "http://schemas.microsoft.com/office/excel/2006/main"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
TC = "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"
CALC_CHAIN = "xl/calcChain.xml"
CONTENT_TYPES = "[Content_Types].xml"
WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"
#: CT_Worksheet children after ``dataValidations`` (ECMA-376 part 1,
#: 18.3.1.99): a new ``dataValidations`` goes before the first of them.
_AFTER_DV = ("hyperlinks", "printOptions", "pageMargins", "pageSetup", "headerFooter",
             "rowBreaks", "colBreaks", "customProperties", "cellWatches", "ignoredErrors",
             "smartTags", "drawing", "legacyDrawing", "legacyDrawingHF", "picture",
             "oleObjects", "controls", "webPublishItems", "tableParts", "extLst")
#: Worksheet elements whose attribute holds a range list that moves with rows.
_RANGE_ATTRS = (("ignoredError", "sqref"), ("protectedRange", "sqref"),
                ("sortState", "ref"), ("sortCondition", "ref"))
_CELL = re.compile(r"^([A-Z]{1,3})(\d+)$")
_CHART = re.compile(r"^xl/charts/chart[^/]*\.xml$")
_PIVOT_CACHE = re.compile(r"^xl/pivotCache/pivotCacheDefinition[^/]*\.xml$")
#: A note shape's row and anchor in legacy VML (``x:`` in Excel's files; the
#: prefix is matched loosely). VML is not always well-formed XML, so it is
#: edited as bytes.
_VML_ROW = re.compile(rb"(<(?:\w+:)?Row>\s*)(\d+)(\s*</(?:\w+:)?Row>)")
_VML_ANCHOR = re.compile(rb"(<(?:\w+:)?Anchor>)([^<]*)(</(?:\w+:)?Anchor>)")


class _Package:
    """The parts the ops rewrite, parsed once and serialised only when
    changed (``dirty``): XML trees by part name, raw bytes for VML.
    ``writer._serialize_like`` keeps each part's original root start tag, so
    a change to a root attribute (a table's ``ref``) goes through
    ``set_root``, which rewrites that attribute in the spliced tag."""

    def __init__(self, z):
        self.z = z
        self.names = set(z.namelist())
        self.sheets = W._sheet_parts(z)
        self.order = tuple(self.sheets)             # the workbook's sheet order
        self._trees, self._raw = {}, {}
        self.dirty, self.removed = set(), set()
        self._root_edits = {}

    def set_root(self, part, name, value):
        root = self.tree(part)
        old = root.get(name)
        if old == value:
            return
        root.set(name, value)
        first = self._root_edits.setdefault(part, {}).get(name, (old, None))[0]
        self._root_edits[part][name] = (first, value)
        self.dirty.add(part)

    def tree(self, part):
        if part not in self._trees:
            source = self.z.read(part)
            self._trees[part] = (source, ET.fromstring(source))
        return self._trees[part][1]

    def raw(self, part) -> bytes:
        if part not in self._raw:
            self._raw[part] = self.z.read(part)
        return self._raw[part]

    def set_raw(self, part, data: bytes):
        if data != self.raw(part):
            self._raw[part] = data
            self.dirty.add(part)

    def rels(self, part) -> list:
        """``(type, target part)`` of ``part``'s internal relationships."""
        folder, base = posixpath.split(part)
        name = posixpath.join(folder, "_rels", base + ".rels")
        if name not in self.names:
            return []
        out = []
        for rel in ET.fromstring(self.z.read(name)).iter(f"{{{NS_REL}}}Relationship"):
            if rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target") or ""
            path = (target[1:] if target.startswith("/")
                    else posixpath.normpath(posixpath.join(folder, target)))
            out.append((rel.get("Type") or "", path))
        return out

    def related(self, part, suffix) -> list:
        return [p for kind, p in self.rels(part) if kind.endswith(suffix) and p in self.names]

    def worksheet(self, title):
        part = self.sheets.get(title)
        if part is None:
            raise KeyError(f"no sheet named {title!r}")
        root = self.tree(part)
        if root.find(f"{{{NS}}}sheetData") is None:
            raise RowOpError(f"{title} is not a worksheet")
        return part, root

    def _spliced(self, part, data: bytes) -> bytes:
        """``data`` with the root attributes ``set_root`` changed rewritten in
        its (original) root start tag."""
        for name, (old, new) in self._root_edits.get(part, {}).items():
            end = W._root_start_end(data)
            head = data[:end]
            pattern = re.compile(rb"(\s" + re.escape(name.encode()) + rb"=)([\"'])"
                                 + re.escape((old or "").encode()) + rb"\2")
            head, n = pattern.subn(lambda m: m.group(1) + m.group(2) + new.encode()
                                   + m.group(2), head, count=1)
            if n != 1:
                raise RowOpError(f"internal error: cannot rewrite {part}'s {name}; "
                                 "nothing was written")
            data = head + data[end:]
        return data

    def replacements(self) -> dict:
        out = {}
        for part in self.dirty:
            if part in self._trees:
                source, root = self._trees[part]
                data = self._spliced(part, W._serialize_like(part, source, root))
                out[part] = W._checked(part, data)
            else:
                out[part] = self._raw[part]
        for part in self.removed:
            out[part] = None
        return out


def _verb(op) -> str:
    return "inserted" if isinstance(op, InsertRows) else "deleted"


def _sqref(text, op) -> str:
    if isinstance(op, InsertRows):
        return refs.sqref_insert(text, op.before, op.count)
    return refs.sqref_delete(text, op.first, op.count)


def _formula(body, title, own, op, where, sheets=()):
    """``(text, lost)``: ``body`` after ``op`` on sheet ``title``. ``where``
    names the formula's home (``Notes!A2``, a defined name) in a refusal;
    ``sheets`` is the workbook's sheet order, which resolves 3-D spans."""
    try:
        if isinstance(op, InsertRows):
            return refs.insert(body, sheet=title, own=own, at=op.before, count=op.count,
                               sheets=sheets), False
        return refs.delete(body, sheet=title, own=own, first=op.first, count=op.count,
                           sheets=sheets)
    except refs.RefsError as exc:
        raise RowOpError(f"{where}: {exc} -- nothing was written") from None


def _formula_or_refuse(text, title, own, op, what, sheets=()):
    if not text:
        return text
    new, gone = _formula(text, title, own, op, what, sheets)
    if gone:
        raise RowOpError(f"{what} would lose its reference to a deleted row ({new}) -- "
                         "change it first")
    return new


def _inside(lo, hi, op) -> bool:
    """Does ``op`` land strictly inside rows ``lo..hi``: some of them move
    and some stay where they are?"""
    if isinstance(op, InsertRows):
        return lo < op.before <= hi
    return lo < op.first and hi > op.last


def _offset_cut(sqref, text, title, op, home) -> bool:
    """Would ``op`` split a rule on ``sqref`` whose formula ``text`` reads
    through a relative row reference a row other than each cell's own (or
    another sheet's row)? Excel splits such a rule in two around the rows
    it inserts or deletes; the writer does not, so the caller refuses.
    ``home``: the rule lives on the edited sheet ``title``."""
    spans = [s for s in (refs.span(p) for p in (sqref or "").split()) if s]
    if not spans or not text:
        return False
    lo, hi = min(s[0] for s in spans), max(s[1] for s in spans)
    anchor = spans[0][0]
    for into, row in refs.relative_rows(text, title, home):
        d = row - anchor
        if home and into:
            if d == 0:
                continue
            a, b = min(lo, lo + d), max(hi, hi + d)
        elif home:
            a, b = lo, hi                             # the cells move, what they read does not
        elif into:
            a, b = lo + d, hi + d                     # what the cells read moves, they do not
        else:
            continue
        if _inside(a, b, op):
            return True
    return False


def _cuts(lo, hi, op) -> bool:
    """Would ``op`` cut rows ``lo..hi``: an insert strictly inside them, or a
    delete of any of them?"""
    if isinstance(op, InsertRows):
        return lo < op.before <= hi
    return lo <= op.last and hi >= op.first


def _hits(row, op) -> bool:
    return isinstance(op, DeleteRows) and op.first <= row <= op.last


def _masters(root) -> dict:
    """Shared formula groups: ``si -> (master cell, text)``."""
    out = {}
    for c in root.iter(f"{{{NS}}}c"):
        f = c.find(f"{{{NS}}}f")
        if f is not None and f.get("t") == "shared" and f.get("ref") is not None and f.text:
            out[f.get("si")] = (c.get("r"), f.text)
    return out


def _unshare(root, mention=None) -> bool:
    """Turn shared formulas into plain ones (each follower gets its master's
    text translated to its own cell) -- every group, or with ``mention`` only
    the groups whose master names that sheet. Returns whether any changed."""
    masters = _masters(root)
    if mention is not None:
        masters = {si: m for si, m in masters.items() if refs.mentions(m[1], mention)}
    if not masters:
        return False
    for c in root.iter(f"{{{NS}}}c"):
        f = c.find(f"{{{NS}}}f")
        if f is None or f.get("t") != "shared" or f.get("si") not in masters:
            continue
        origin, text = masters[f.get("si")]
        if c.get("r") != origin:
            f.text = Translator("=" + text, origin=origin).translate_formula(c.get("r"))[1:]
        for name in ("t", "si", "ref"):
            f.attrib.pop(name, None)
    return True


def _sheet_formulas(title, data, op, lost, sheets=()):
    """Every formula on the edited sheet, in the old coordinates, before
    the rows move. An array formula the op would cut is refused, its master
    row deleted or not; one deleted whole goes with its rows."""
    move = op.move()
    for row in data.findall(f"{{{NS}}}row"):
        r = W._row_number(title, row)
        hit = _hits(r, op)
        for c in row.findall(f"{{{NS}}}c"):
            f = c.find(f"{{{NS}}}f")
            if f is None:
                continue
            if f.get("t") == "dataTable":
                raise RowOpError(f"{title}!{c.get('r')}: a data table cannot be moved by the "
                                 "writer")
            if f.get("t") == "array" and f.get("ref"):
                got = refs.span(f.get("ref"))
                whole = got is not None and hit and op.first <= got[0] and got[1] <= op.last
                if got and _cuts(*got, op) and not whole:
                    raise RowOpError(f"{title}!{f.get('ref')}: an array formula spans the rows "
                                     f"being {_verb(op)} -- the writer does not resize it")
                if not hit:
                    f.set("ref", _sqref(f.get("ref"), op))
            if hit or not f.text:
                continue
            text, gone = _formula(f.text, title, True, op, f"{title}!{c.get('r')}", sheets)
            f.text = text
            if gone:
                col, _r = W._parse_ref(title, c.get("r"))
                lost.append((title, f"{col}{move.rows(r, r)[0]}", text))


def _move_rows(title, data, op):
    move = op.move()
    for row in list(data.findall(f"{{{NS}}}row")):
        r = W._row_number(title, row)
        if _hits(r, op):
            data.remove(row)
            continue
        got = move.rows(r, r)
        if got is None:
            raise RowOpError(f"{title}: row {r} would be pushed past Excel's last row "
                             f"({refs.MAX_ROW})")
        new = got[0]
        if new == r:
            continue
        row.set("r", str(new))
        for c in row.findall(f"{{{NS}}}c"):
            col, _old = W._parse_ref(title, c.get("r"))
            c.set("r", f"{col}{new}")


def _merges(title, root, op):
    mc = root.find(f"{{{NS}}}mergeCells")
    if mc is None:
        return
    for m in mc.findall(f"{{{NS}}}mergeCell"):
        got = refs.span(m.get("ref") or "")
        if got and _cuts(*got, op):
            raise RowOpError(f"{title}!{m.get('ref')}: merged cells across the rows being "
                             f"{_verb(op)} -- unmerge them first")
        m.set("ref", _sqref(m.get("ref"), op))


def _anchor(sqref):
    """``(column, row)`` of a range list's first cell, or None."""
    parts = (sqref or "").split()
    m = _CELL.match(parts[0].split(":")[0].replace("$", "")) if parts else None
    return (m.group(1), int(m.group(2))) if m else None


def _reanchor(text, old_sqref, new_sqref, op):
    """A conditional format's or a data validation's formula is written as if
    it sat in its range's top-left cell. When a delete takes that cell, Excel
    re-anchors the formula on the new top-left cell: its relative references
    travel there first (``Translator``, column and row), then the delete's
    shift applies, so a rule that read its own row still does."""
    if not isinstance(op, DeleteRows) or not text:
        return text
    t, n = _anchor(old_sqref), _anchor(new_sqref)
    if t is None or n is None:
        return text
    n_old = n[1] if n[1] < op.first else n[1] + op.count   # the new top-left, before the delete
    if (n[0], n_old) == t:
        return text
    return Translator("=" + text, origin=f"{t[0]}{t[1]}").translate_formula(
        f"{n[0]}{n_old}")[1:]


def _number(text) -> bool:
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def _rule(title, old, new, targets, op, own, what, sheets, home_title=None,
          relative=True) -> bool:
    """Move the formulas ``targets`` (``(element, attribute or None for its
    text)``) of a rule on ``old`` (now ``new``): refuse an op that would
    split it, re-anchor, shift, refuse a lost reference."""
    changed = False
    where = f"{home_title or title}: {what} on {new or old}"
    for el, attr in targets:
        text = el.get(attr) if attr else el.text
        if not text:
            continue
        if relative and _offset_cut(old, text, title, op, own):
            raise RowOpError(f"{home_title or title}: {what} on {old} reads {text} relative to "
                             f"its cells; Excel would split it around the rows being "
                             f"{_verb(op)} and the writer does not -- change the rule first")
        body = _reanchor(text, old, new, op) if own and relative else text
        moved = _formula_or_refuse(body, title, own, op, where, sheets)
        if moved != text:
            if attr:
                el.set(attr, moved)
            else:
                el.text = moved
            changed = True
    return changed


def _formats(title, root, op, own=True, home=None, sheets=()) -> bool:
    """Conditional formats (their formulas and formula thresholds) and data
    validations: on the edited sheet their ranges and formulas move (an
    emptied one is removed; a formula is re-anchored when its top-left cell
    is deleted); on another sheet (``own`` False, ``home`` its title) only
    formulas that name the edited sheet change. A rule reading another row
    relatively that the op would split is refused."""
    changed = False
    for cf in root.findall(f"{{{NS}}}conditionalFormatting"):
        old = cf.get("sqref") or ""
        new = old
        if own:
            new = _sqref(old, op)
            if not new:
                root.remove(cf)
                changed = True
                continue
            if new != old:
                cf.set("sqref", new)
                changed = True
        targets = [(fe, None) for fe in cf.iter(f"{{{NS}}}formula")]
        targets += [(v, "val") for v in cf.iter(f"{{{NS}}}cfvo")
                    if v.get("val") and not _number(v.get("val"))]
        changed = _rule(title, old, new, targets, op, own, "a conditional format", sheets,
                        home) or changed
    dvs = root.find(f"{{{NS}}}dataValidations")
    if dvs is not None:
        for dv in dvs.findall(f"{{{NS}}}dataValidation"):
            old = dv.get("sqref") or ""
            new = old
            if own:
                new = _sqref(old, op)
                if not new:
                    dvs.remove(dv)
                    changed = True
                    continue
                if new != old:
                    dv.set("sqref", new)
                    changed = True
            targets = [(fe, None) for fe in (dv.find(f"{{{NS}}}formula1"),
                                             dv.find(f"{{{NS}}}formula2")) if fe is not None]
            changed = _rule(title, old, new, targets, op, own, "a data validation", sheets,
                            home) or changed
        if own:
            if len(dvs.findall(f"{{{NS}}}dataValidation")) == 0:
                root.remove(dvs)
            else:
                dvs.set("count", str(len(dvs.findall(f"{{{NS}}}dataValidation"))))
    return changed


def _sheet_extras(title, root, op):
    """Hyperlinks, row breaks, the dimension, the auto filter and the other
    range attributes of the edited sheet. The view (pane, selection) stays
    where it was, as Excel leaves it."""
    links = root.find(f"{{{NS}}}hyperlinks")
    if links is not None:
        for h in links.findall(f"{{{NS}}}hyperlink"):
            got = refs.span(h.get("ref") or "")
            if got and isinstance(op, DeleteRows) and _cuts(*got, op):
                raise RowOpError(f"{title}!{h.get('ref')} holds a hyperlink on a deleted row -- "
                                 "remove it first")
            h.set("ref", _sqref(h.get("ref"), op))
    breaks = root.find(f"{{{NS}}}rowBreaks")
    if breaks is not None:
        for brk in breaks.findall(f"{{{NS}}}brk"):
            n = int(brk.get("id", "0"))
            got = op.move().rows(n, n)
            if got is None:
                breaks.remove(brk)
                continue
            brk.set("id", str(got[0]))
        kept = breaks.findall(f"{{{NS}}}brk")
        breaks.set("count", str(len(kept)))
        if breaks.get("manualBreakCount") is not None:
            breaks.set("manualBreakCount",
                       str(sum(1 for b in kept if b.get("man") in ("1", "true"))))
    dim = root.find(f"{{{NS}}}dimension")
    if dim is not None and dim.get("ref"):
        dim.set("ref", _sqref(dim.get("ref"), op) or "A1")
    auto = root.find(f"{{{NS}}}autoFilter")
    if auto is not None and auto.get("ref"):
        got = refs.span(auto.get("ref"))
        if got and _cuts(*got, op):
            raise RowOpError(f"{title}!{auto.get('ref')}: the auto filter spans the rows being "
                             f"{_verb(op)} -- clear it first")
        auto.set("ref", _sqref(auto.get("ref"), op))
    holders = [root]
    for path in ("autoFilter", "ignoredErrors", "protectedRanges",
                 "customSheetViews/customSheetView",
                 "customSheetViews/customSheetView/autoFilter"):
        holders += root.findall("/".join(f"{{{NS}}}{p}" for p in path.split("/")))
    holders += [ss for h in list(holders) for ss in h.findall(f"{{{NS}}}sortState")]
    for parent in holders:
        for tag, attr in _RANGE_ATTRS:
            for el in parent.findall(f"{{{NS}}}{tag}"):
                old = el.get(attr)
                if not old:
                    continue
                new = _sqref(old, op)
                if new:
                    el.set(attr, new)
                else:
                    parent.remove(el)                 # it would point at other cells
    for tag in ("ignoredErrors", "protectedRanges"):
        for el in root.findall(f"{{{NS}}}{tag}"):
            if len(el) == 0:
                root.remove(el)


def _extensions(title, root, op, own=True, home=None, sheets=()) -> bool:
    """The Excel 2010 extensions (x14 data validations, conditional formats,
    sparklines), each rule with its range: on the edited sheet the
    ``xm:sqref`` moves and an emptied one takes its rule with it, unread;
    a surviving validation or format is re-anchored and refused when the op
    would split it, as the sheet-level ones are; every ``xm:f`` naming the
    edited sheet moves."""
    ext = root.find(f"{{{NS}}}extLst")
    if ext is None:
        return False
    changed = False
    parents = {child: parent for parent in ext.iter() for child in parent}
    done = set()
    for sq in list(ext.iter(f"{{{XM}}}sqref")):
        holder = parents.get(sq)
        if holder is None:
            continue
        formulas = list(holder.iter(f"{{{XM}}}f"))
        done.update(formulas)
        old = sq.text or ""
        new = old
        if own:
            new = _sqref(old, op)
            if not new:
                outer = parents.get(holder)
                if outer is not None:
                    outer.remove(holder)
                    if outer.get("count") is not None:
                        outer.set("count", str(len(outer)))
                    changed = True
                continue
            if new != old:
                sq.text, changed = new, True
        rule = holder.tag.rsplit("}", 1)[-1] in ("dataValidation", "conditionalFormatting")
        changed = _rule(title, old, new, [(f, None) for f in formulas], op, own,
                        "an Excel 2010 extension rule", sheets, home, relative=rule) or changed
    for f in ext.iter(f"{{{XM}}}f"):
        if f in done:
            continue
        text = _formula_or_refuse(f.text, title, own, op,
                                  f"{home or title}: an Excel 2010 extension", sheets)
        if text != f.text:
            f.text, changed = text, True
    return changed


def _edit_sheet(pkg, title, op, lost):
    part, root = pkg.worksheet(title)
    pkg.dirty.add(part)
    _unshare(root)
    data = root.find(f"{{{NS}}}sheetData")
    _merges(title, root, op)
    _sheet_formulas(title, data, op, lost, pkg.order)
    _move_rows(title, data, op)
    _formats(title, root, op, sheets=pkg.order)
    _sheet_extras(title, root, op)
    _extensions(title, root, op, sheets=pkg.order)
    return part


def _is_uid(name) -> bool:
    """A revision id (``xr:uid``): Excel gives each validation its own, so it
    says nothing about what the validation does."""
    return name == "uid" or name.endswith("}uid")


def _signature(dv):
    attrs = tuple(sorted((k, v) for k, v in dv.attrib.items()
                         if k != "sqref" and not _is_uid(k)))
    return attrs, tuple((child.tag, child.text) for child in dv)


def _translated(dv, origin, dest):
    """A copy of validation ``dv`` whose formulas, written for cell
    ``origin``, are written for ``dest`` instead (Excel's copy); None when a
    formula cannot be moved there."""
    out = copy.deepcopy(dv)
    for tag in ("formula1", "formula2"):
        fe = out.find(f"{{{NS}}}{tag}")
        if fe is None or not fe.text or origin == dest:
            continue
        try:
            fe.text = Translator("=" + fe.text, origin=origin).translate_formula(dest)[1:]
        except Exception:                             # noqa: BLE001 -- openpyxl's own errors
            return None
    return out


def _covered(sqref, row, skip) -> list:
    """The column letters of ``sqref``'s ranges that cover ``row``."""
    out = []
    for part in (sqref or "").split():
        ends = part.split(":")
        m1, m2 = _CELL.match(ends[0]), _CELL.match(ends[-1])
        if not (m1 and m2) or not int(m1.group(2)) <= row <= int(m2.group(2)):
            continue
        for n in range(column_index_from_string(m1.group(1)),
                       column_index_from_string(m2.group(1)) + 1):
            letter = get_column_letter(n)
            if letter not in skip and letter not in out:
                out.append(letter)
    return out


def _within(ranges, cell) -> bool:
    """Is ``cell`` (``B5``) inside one of ``ranges`` (``B2:B9``, ``C4``)?"""
    m = _CELL.match(cell)
    col, row = column_index_from_string(m.group(1)), int(m.group(2))
    for part in ranges:
        ends = [_CELL.match(e.replace("$", "")) for e in part.split(":")]
        if not all(ends):
            continue
        cols = [column_index_from_string(e.group(1)) for e in ends]
        rows = [int(e.group(2)) for e in ends]
        if min(cols) <= col <= max(cols) and min(rows) <= row <= max(rows):
            return True
    return False


def _copy_validations(root, src_root, op):
    """The prototype sheet's sheet-level validations onto the copied cells,
    their formulas moved as Excel's copy moves them: added to an equivalent
    validation of the target sheet when there is one (the same rule once
    written for that validation's own first cell; revision ids aside), else
    a copy of the prototype's written for the first copied cell."""
    src = src_root.find(f"{{{NS}}}dataValidations")
    if src is None:
        return
    dvs = root.find(f"{{{NS}}}dataValidations")
    for sdv in src.findall(f"{{{NS}}}dataValidation"):
        start = _anchor(sdv.get("sqref"))
        cells = []
        for k in range(op.times):
            for offset in range(op.width):
                dst = op.before + k * op.width + offset
                cells += [f"{c}{dst}" for c in _covered(sdv.get("sqref"), op.first + offset,
                                                        op.skip)]
        if not cells or start is None:
            continue
        # A copied cell reads the prototype's rule moved by the rows it moved
        # (Excel's copy), so the rule written for any cell ``A`` of the target
        # sheet is the prototype's translated from its own first cell to ``A``.
        origin = f"{start[0]}{start[1]}"
        if dvs is None:
            dvs = ET.Element(f"{{{NS}}}dataValidations")
            after = {f"{{{NS}}}{t}" for t in _AFTER_DV}
            at = next((i for i, child in enumerate(root) if child.tag in after), len(root))
            root.insert(at, dvs)
        match = None
        for d in dvs.findall(f"{{{NS}}}dataValidation"):
            there = _anchor(d.get("sqref"))
            if there is None:
                continue
            moved = _translated(sdv, origin, f"{there[0]}{there[1]}")
            if moved is not None and _signature(moved) == _signature(d):
                match = d
                break
        if match is None:
            match = _translated(sdv, origin, cells[0])
            if match is None:
                raise RowOpError(f"{op.source}!{sdv.get('sqref')}: a data validation whose "
                                 "formula cannot be copied to the new rows")
            match.set("sqref", "")
            dvs.append(match)
        have = (match.get("sqref") or "").split()
        match.set("sqref", " ".join(have + [c for c in cells if not _within(have, c)]))
    if dvs is not None:
        dvs.set("count", str(len(dvs.findall(f"{{{NS}}}dataValidation"))))


def _copied_cell(op, c, col, dst, masters):
    ref = f"{col}{dst}"
    new = ET.Element(f"{{{NS}}}c", {"r": ref})
    if c.get("s") is not None:
        new.set("s", c.get("s"))
    f = c.find(f"{{{NS}}}f")
    if f is None:
        if c.get("t") is not None:
            new.set("t", c.get("t"))
        for child in c:
            new.append(copy.deepcopy(child))
        return new
    if f.get("t") in ("array", "dataTable"):
        raise RowOpError(f"{op.source}!{c.get('r')}: a prototype cell holds an array formula "
                         "or a data table -- the writer copies plain formulas only")
    text = f.text
    if f.get("t") == "shared" and not text:
        origin, master = masters.get(f.get("si"), (None, None))
        if master is None:
            raise RowOpError(f"{op.source}!{c.get('r')}: a shared formula without its master")
        text = Translator("=" + master, origin=origin).translate_formula(c.get("r"))[1:]
    if text:
        ET.SubElement(new, f"{{{NS}}}f").text = Translator(
            "=" + text, origin=c.get("r")).translate_formula(ref)[1:]
    return new


def _grow_dimension(root, cells):
    """The sheet's ``dimension`` widened to hold ``cells`` (copied ones may
    lie below or right of it)."""
    dim = root.find(f"{{{NS}}}dimension")
    if dim is None or not cells:
        return
    corners = [m for m in (_CELL.match(x.replace("$", ""))
                           for x in (dim.get("ref") or "").split(":") + list(cells)) if m]
    cols = [column_index_from_string(m.group(1)) for m in corners]
    rows = [int(m.group(2)) for m in corners]
    lo = f"{get_column_letter(min(cols))}{min(rows)}"
    hi = f"{get_column_letter(max(cols))}{max(rows)}"
    dim.set("ref", lo if lo == hi else f"{lo}:{hi}")


def _copy_rows(pkg, op):
    """The prototype rows into the gap the insert left."""
    part, root = pkg.worksheet(op.sheet)
    _src_part, src_root = pkg.worksheet(op.source)
    data = root.find(f"{{{NS}}}sheetData")
    masters = _masters(src_root)
    source_rows = {W._row_number(op.source, r): r
                   for r in src_root.find(f"{{{NS}}}sheetData").findall(f"{{{NS}}}row")}
    new_rows = []
    for k in range(op.times):
        for offset in range(op.width):
            dst = op.before + k * op.width + offset
            row = ET.Element(f"{{{NS}}}row", {"r": str(dst)})
            src = source_rows.get(op.first + offset)
            if src is not None:
                for name, value in src.attrib.items():
                    if name not in ("r", "spans"):
                        row.set(name, value)
                for c in src.findall(f"{{{NS}}}c"):
                    col, _r = W._parse_ref(op.source, c.get("r"))
                    if col in op.skip:
                        continue
                    row.append(_copied_cell(op, c, col, dst, masters))
            new_rows.append(row)
    children = list(data)
    at = next((i for i, r in enumerate(children)
               if W._row_number(op.sheet, r) >= op.before), len(children))
    for n, row in enumerate(new_rows):
        data.insert(at + n, row)
    _grow_dimension(root, [c.get("r") for row in new_rows for c in row])
    _copy_validations(root, src_root, op)
    pkg.dirty.add(part)


def _drop_calc_chain(pkg):
    if CALC_CHAIN not in pkg.names or CALC_CHAIN in pkg.removed:
        return
    pkg.removed.add(CALC_CHAIN)
    types = pkg.tree(CONTENT_TYPES)
    for o in types.findall(f"{{{CT}}}Override"):
        if o.get("PartName") == "/" + CALC_CHAIN:
            types.remove(o)
            pkg.dirty.add(CONTENT_TYPES)
    if WORKBOOK_RELS in pkg.names:
        rels = pkg.tree(WORKBOOK_RELS)
        for r in rels.findall(f"{{{NS_REL}}}Relationship"):
            if (r.get("Target") or "").endswith("calcChain.xml"):
                rels.remove(r)
                pkg.dirty.add(WORKBOOK_RELS)


def _pivots(pkg, title):
    for name in sorted(pkg.names):
        if not _PIVOT_CACHE.match(name):
            continue
        for src in pkg.tree(name).iter(f"{{{NS}}}worksheetSource"):
            if (src.get("sheet") or "").casefold() == title.casefold():
                raise RowOpError(f"a pivot table reads {title} ({src.get('ref')}) -- the writer "
                                 "cannot move its source; remove the pivot or rebuild the book")


def _zero_based(n, op):
    """A 0-based row index (VML, drawings) after ``op``; one on a deleted row
    moves to the first row below the deleted ones."""
    got = op.move().rows(n + 1, n + 1)
    return (got[0] if got else op.first) - 1


def _notes(pkg, part, title, op):
    for name, tag in [(p, f"{{{NS}}}comment") for p in pkg.related(part, "/comments")] + \
                     [(p, f"{{{TC}}}threadedComment")
                      for p in pkg.related(part, "/threadedComment")]:
        root, changed = pkg.tree(name), False
        for c in root.iter(tag):
            ref = c.get("ref") or ""
            got = refs.span(ref)
            if got is None:
                continue
            if isinstance(op, DeleteRows) and _cuts(*got, op):
                raise RowOpError(f"{title}!{ref} holds a note on a deleted row -- move or "
                                 "delete the note first")
            new = _sqref(ref, op)
            if new != ref:
                c.set("ref", new)
                changed = True
        if changed:
            pkg.dirty.add(name)
    for name in pkg.related(part, "/vmlDrawing"):
        def row(m):
            return m.group(1) + str(_zero_based(int(m.group(2)), op)).encode() + m.group(3)

        def anchor(m):
            parts = m.group(2).decode().split(",")
            if len(parts) == 8:
                for i in (2, 6):
                    moved = _zero_based(int(parts[i].strip()), op)
                    if moved != int(parts[i].strip()):
                        parts[i] = f" {moved}"
            return m.group(1) + ",".join(parts).encode() + m.group(3)

        pkg.set_raw(name, _VML_ANCHOR.sub(anchor, _VML_ROW.sub(row, pkg.raw(name))))


def _drawings(pkg, part, title, op):
    for name in pkg.related(part, "/drawing"):
        root, changed = pkg.tree(name), False
        for anchor in root:
            for which in ("from", "to"):
                end = anchor.find(f"{{{XDR}}}{which}")
                el = end.find(f"{{{XDR}}}row") if end is not None else None
                if el is None or el.text is None:
                    continue
                n = int(el.text)
                if which == "from" and _hits(n + 1, op):
                    raise RowOpError(f"{title}: a picture, chart or shape is anchored on deleted "
                                     f"row {n + 1} -- move it first")
                got = op.move().rows(n + 1, n + 1)
                if got is not None:
                    moved = got[0] - 1
                elif isinstance(op, InsertRows):
                    moved = refs.MAX_ROW - 1
                else:
                    # A bottom edge on a deleted row: the top of the first row
                    # below, as Excel leaves it (0-based ``op.first - 1``).
                    moved = op.first - 1
                    off = end.find(f"{{{XDR}}}rowOff")
                    if off is not None and off.text != "0":
                        off.text, changed = "0", True
                if moved != n:
                    el.text, changed = str(moved), True
        if changed:
            pkg.dirty.add(name)


def _tables(pkg, part, title, op):
    for name in pkg.related(part, "/table"):
        root = pkg.tree(name)
        got = refs.span(root.get("ref") or "")
        if got is None:
            continue
        if _cuts(*got, op):
            raise RowOpError(f"{title}: table {root.get('displayName') or root.get('name')} "
                             f"({root.get('ref')}) spans the rows being {_verb(op)} -- the "
                             "writer does not resize tables")
        new = _sqref(root.get("ref"), op)
        if new == root.get("ref"):
            continue
        pkg.set_root(name, "ref", new)
        for el in root.iter():
            if el is not root and el.get("ref"):
                el.set("ref", _sqref(el.get("ref"), op))


def _other_sheets(pkg, title, op, lost):
    for other, part in pkg.sheets.items():
        if other == title:
            continue
        root = pkg.tree(part)
        if root.find(f"{{{NS}}}sheetData") is None:
            continue                                   # a chartsheet
        changed = _unshare(root, mention=title)
        for row in root.iter(f"{{{NS}}}row"):
            for c in row.findall(f"{{{NS}}}c"):
                f = c.find(f"{{{NS}}}f")
                if f is None or not f.text or not refs.could_mention(f.text, title):
                    continue
                text, gone = _formula(f.text, title, False, op, f"{other}!{c.get('r')}",
                                      pkg.order)
                if text != f.text:
                    f.text, changed = text, True
                if gone:
                    lost.append((other, c.get("r"), text))
        changed = _formats(title, root, op, own=False, home=other, sheets=pkg.order) or changed
        changed = _extensions(title, root, op, own=False, home=other,
                              sheets=pkg.order) or changed
        if changed:
            pkg.dirty.add(part)


def _names(pkg, title, op):
    root = pkg.tree(W.WORKBOOK)
    names = root.find(f"{{{NS}}}definedNames")
    if names is None:
        return
    for dn in names.findall(f"{{{NS}}}definedName"):
        if not dn.text or not refs.could_mention(dn.text, title):
            continue
        new = _formula_or_refuse(dn.text, title, False, op, f"the defined name {dn.get('name')}",
                                 pkg.order)
        if new != dn.text:
            dn.text = new
            pkg.dirty.add(W.WORKBOOK)


def _charts(pkg, title, op):
    for name in sorted(pkg.names):
        if not _CHART.match(name):
            continue
        root, changed = pkg.tree(name), False
        for el in root.iter():
            if not el.tag.endswith("}f") or not el.text or not refs.could_mention(el.text, title):
                continue
            new = _formula_or_refuse(el.text, title, False, op, f"a chart series ({name})",
                                     pkg.order)
            if new != el.text:
                el.text, changed = new, True
        if changed:
            pkg.dirty.add(name)


def _pivot_tables(pkg, part, title):
    if pkg.related(part, "/pivotTable"):
        raise RowOpError(f"{title} holds a pivot table -- the writer cannot move it; remove it "
                         "or rebuild the book")


def _track(tracked, fresh, op):
    """Lost cells across ops: the ones already lost move with ``op`` (or go
    with its deleted rows); the ones ``op`` lost join them."""
    out = []
    for sheet, col, row in tracked:
        if sheet == op.sheet:
            got = op.move().rows(row, row)
            if got is None:
                continue
            row = got[0]
        out.append((sheet, col, row))
    for sheet, cell, _text in fresh:
        m = _CELL.match(cell)
        key = (sheet, m.group(1), int(m.group(2)))
        if key not in out:
            out.append(key)
    return out


def _formula_at(pkg, sheet, ref):
    for c in pkg.tree(pkg.sheets[sheet]).iter(f"{{{NS}}}c"):
        if c.get("r") == ref:
            f = c.find(f"{{{NS}}}f")
            return f.text if f is not None else None
    return None


def apply(z, ops, *, lost_ok=frozenset()) -> Outcome:
    """Apply ``ops`` to the package open as ``z`` (a ``zipfile.ZipFile``);
    nothing is written here (``writer.edit`` writes the outcome). Raises
    ``RowOpError`` (nothing to write) and ``KeyError`` for an unknown sheet.
    A cell formula an op leaves reading ``#REF!`` is followed through the
    ops after it: reported where it ends up, or not at all when a later op
    deletes it."""
    pkg = _Package(z)
    tracked = []
    try:
        for op in ops:
            if not isinstance(op, (InsertRows, DeleteRows)):
                raise TypeError(f"not a row op: {op!r}")
            part, _root = pkg.worksheet(op.sheet)
            if isinstance(op, InsertRows):
                pkg.worksheet(op.source)
                if op.before + op.count - 1 > refs.MAX_ROW:
                    raise RowOpError(f"{op.sheet}: {op.count} rows inserted above row "
                                     f"{op.before} would run past Excel's last row "
                                     f"({refs.MAX_ROW})")
            _pivots(pkg, op.sheet)
            _pivot_tables(pkg, part, op.sheet)
            fresh = []
            part = _edit_sheet(pkg, op.sheet, op, fresh)
            _notes(pkg, part, op.sheet, op)
            _drawings(pkg, part, op.sheet, op)
            _tables(pkg, part, op.sheet, op)
            _other_sheets(pkg, op.sheet, op, fresh)
            _names(pkg, op.sheet, op)
            _charts(pkg, op.sheet, op)
            if isinstance(op, InsertRows):
                _copy_rows(pkg, op)
            tracked = _track(tracked, fresh, op)
        if ops:
            _drop_calc_chain(pkg)
    except refs.RefsError as exc:
        raise RowOpError(str(exc)) from None
    lost = []
    for sheet, col, row in tracked:
        text = _formula_at(pkg, sheet, f"{col}{row}")
        if text and "#REF!" in text.upper():
            lost.append((sheet, f"{col}{row}", text))
    refused = [x for x in lost if x[0] not in lost_ok]
    if refused:
        shown = "; ".join(f"{s}!{r} ({t})" for s, r, t in refused[:5])
        more = f"; and {len(refused) - 5} more" if len(refused) > 5 else ""
        raise RowOpError(f"deleting the rows would leave formulas pointing at nothing: "
                         f"{shown}{more} -- nothing was written")
    return Outcome(replacements=pkg.replacements(), lost=[x for x in lost if x[0] in lost_ok])