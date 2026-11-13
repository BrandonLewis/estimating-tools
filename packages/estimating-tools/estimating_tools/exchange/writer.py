"""Edit cells inside an .xlsx without loading it through openpyxl, so charts,
images, validations, VBA and every untouched part survive byte for byte
(contract rule 13). Only the named sheets' XML and ``docProps/custom.xml``
(created, with its content type and package relationship, when the book has
none) are rewritten -- with one deliberate exception: ``full_calc_on_load=True``
also rewrites ``xl/workbook.xml`` to set ``fullCalcOnLoad="1"`` on its
``<calcPr>`` (added at its schema position when absent), so Excel
recalculates every formula on open. A caller that changes a cell a formula
reads, or writes a :class:`Formula` (which carries no cached value), asks
for it. Strings are inline strings; ``sharedStrings.xml`` is never
touched. A cell that holds a formula is refused, never overwritten: a shared
formula's followers would be orphaned and ``xl/calcChain.xml`` left pointing
at a cell with no formula, which Excel reports as needing repair.

Public surface: :func:`write` (cells and properties in one atomic rewrite),
the thin wrappers :func:`write_cells` and :func:`set_custom_properties`, and
:func:`write_cached`, which sets or removes the cached values of formula
cells and nothing else. ``edit(names=...)`` sets workbook-scoped defined
names in ``xl/workbook.xml``.
Cell values are ``str | int | float | bool | None`` (``None`` clears) or a
:class:`Formula`, which goes only into a cell that holds no formula today;
any other type, including ``Decimal``, is refused. Errors: ``KeyError`` for an
unknown sheet, ``ValueError`` for everything else (bad reference, formula
cell, non-finite number, character XML cannot carry, chartsheet, a defined
name Excel refuses). Nothing is written on any error. :func:`edit` adds
whole-row inserts and deletes (``exchange.rowops``) before the cell writes,
in the same rewrite."""
from __future__ import annotations

import contextlib
import io
import math
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CP = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
NS_VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"
CUSTOM = "docProps/custom.xml"
WORKBOOK = "xl/workbook.xml"

_REF = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$")
_MAX_COL, _MAX_ROW = 16384, 1048576          # XFD, 1048576
_BAD_CHAR = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_XMLNS = re.compile(rb'\sxmlns:([\w.-]+)=(["\'])(.*?)\2')
_PROLOG_ITEM = re.compile(rb"\s*(?:<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>)", re.DOTALL)
_DEFAULT_BINDINGS = (("", NS), ("r", NS_R), ("cp", NS_CP), ("vt", NS_VT))


@dataclass(frozen=True)
class Formula:
    """A formula to place in a cell: ``Formula("=SUM(A1:A3)")`` is written as
    ``<f>SUM(A1:A3)</f>`` (the leading ``=`` dropped; text without one is
    stored as given), with no cached value, so Excel computes it on open (a
    HeavyBook book asks for a full calculation on load). The cell must hold
    no formula today: an existing formula is never overwritten."""
    text: str

    @property
    def body(self) -> str:
        return self.text[1:] if self.text.startswith("=") else self.text


@dataclass(frozen=True)
class CachedError:
    """An error result to cache on a formula cell (``#N/A``, ``#DIV/0!``, ...)."""
    code: str


def _root_start_end(data: bytes) -> int:
    """Offset just past the root element's start tag (``>`` inside quoted
    attribute values does not count)."""
    pos = 0
    while True:
        m = _PROLOG_ITEM.match(data, pos)
        if not m:
            break
        pos = m.end()
    quote = None
    for i in range(pos, len(data)):
        ch = data[i:i + 1]
        if quote:
            if ch == quote:
                quote = None
        elif ch in (b'"', b"'"):
            quote = ch
        elif ch == b">":
            return i + 1
    raise ValueError("no root start tag")


def _root_declarations(data: bytes) -> list:
    """The ``(prefix, uri)`` namespace declarations on the root element."""
    found = []
    for event, value in ET.iterparse(io.BytesIO(data), events=("start-ns", "start")):
        if event == "start":
            break
        found.append(value)
    return found


def _all_declarations(data: bytes) -> list:
    """Every ``(prefix, uri)`` namespace declaration in ``data``, the root's
    first: the first binding of each prefix, and of each namespace, wins.
    Excel declares ``x14`` and ``xm`` on the elements of an ``extLst``, not on
    the root; binding them too keeps their prefixes through a rewrite."""
    found, prefixes, uris = [], set(), set()
    for _event, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        if prefix in prefixes or uri in uris:
            continue
        prefixes.add(prefix)
        uris.add(uri)
        found.append((prefix, uri))
    return found


@contextlib.contextmanager
def _source_namespaces(source: bytes):
    """Bind the source's own prefixes (the root's and those declared below it)
    in ElementTree's process-wide table for one serialisation, then restore
    the table, so other users of it (openpyxl without lxml) are unaffected.
    Where the source does not declare ``r`` or ``vt``, the usual prefixes are
    bound so new elements read well."""
    table = getattr(ET, "_namespace_map", None)
    saved = dict(table) if table is not None else None
    try:
        declared = _all_declarations(source)
        bound_uris = {uri for _p, uri in declared}
        bound_prefixes = {p for p, _u in declared}
        for prefix, uri in _DEFAULT_BINDINGS[1:]:
            if prefix in ("r", "vt") and prefix not in bound_prefixes and uri not in bound_uris:
                ET.register_namespace(prefix, uri)
        for prefix, uri in declared:
            if prefix == "xml":
                continue
            if re.fullmatch(r"ns\d+", prefix):
                # register_namespace refuses these; bind them in the table
                # directly (uri -> prefix) when it exists.
                if table is not None:
                    for known in [k for k, v in table.items() if v == prefix]:
                        del table[known]
                    table[uri] = prefix
                continue
            ET.register_namespace(prefix, uri)
        yield
    finally:
        if table is not None:
            table.clear()
            table.update(saved)
        # Without the private table there is nothing to restore; the writer's
        # own bindings stay registered rather than leaving ns0/ns1 prefixes.


def _serialize_like(part: str, source: bytes, root) -> bytes:
    """Serialise ``root`` with the original prolog and root start tag of
    ``source`` spliced over ElementTree's. ElementTree drops ``standalone``,
    unused ``xmlns:*`` declarations and renames prefixes, so ``mc:Ignorable``
    would name undeclared prefixes and Excel would call the file corrupt.
    The source's own prefixes are used for the body, so the body matches the
    restored start tag whatever prefix the source used for its namespaces."""
    if getattr(ET, "_namespace_map", None) is None:
        for prefix, uri in _DEFAULT_BINDINGS:
            ET.register_namespace(prefix, uri)
    with _source_namespaces(source):
        out = ET.tostring(root, encoding="UTF-8")
    end = _root_start_end(out)
    head = source[:_root_start_end(source)]
    # A prefix ElementTree needed that the original root did not declare (the
    # source declared it on a child, or the writer added a new element).
    declared = {m.group(1): m.group(3) for m in _XMLNS.finditer(head)}
    extra = b""
    for m in _XMLNS.finditer(out[:end]):
        prefix = m.group(1)
        if prefix not in declared:
            extra += m.group(0)
        elif declared[prefix] != m.group(3):
            raise ValueError(f"internal error: rewritten {part} would rebind prefix "
                             f"{prefix.decode()!r}; nothing was written")
    return head[:-1] + extra + head[-1:] + out[end:]


def _checked(part: str, data: bytes) -> bytes:
    try:
        ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"internal error: rewritten {part} is not well-formed XML; "
                         "nothing was written") from exc
    return data


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _sheet_parts(z: zipfile.ZipFile) -> dict:
    """sheet title -> zip entry name, via workbook.xml and its rels."""
    wb = ET.fromstring(z.read(WORKBOOK))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{{{NS_REL}}}Relationship")}
    parts = {}
    for s in wb.iter(f"{{{NS}}}sheet"):
        target = targets[s.get(f"{{{NS_R}}}id")]
        # A leading slash means package-absolute; otherwise relative to xl/.
        parts[s.get("name")] = target[1:] if target.startswith("/") else "xl/" + target
    return parts


def _check_value(where: str, value) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, Formula):
        if not isinstance(value.text, str) or not value.body.strip():
            raise ValueError(f"{where}: a formula needs its text")
        if _BAD_CHAR.search(value.text):
            raise ValueError(f"{where} holds a character XML cannot carry")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where} is {value!r}; only finite numbers can be written")
    elif isinstance(value, str):
        if _BAD_CHAR.search(value):
            raise ValueError(f"{where} holds a character XML cannot carry")
    elif not isinstance(value, int):
        raise ValueError(f"{where}: cannot write a {type(value).__name__}")


def _parse_ref(title: str, ref) -> tuple:
    m = _REF.match(ref) if isinstance(ref, str) else None
    if not m or _col_index(m.group(1)) > _MAX_COL or int(m.group(2)) > _MAX_ROW:
        raise ValueError(f"{title}!{ref}: not a cell reference")
    return m.group(1), int(m.group(2))


def _row_number(title: str, row_el) -> int:
    try:
        return int(row_el.get("r"))
    except (TypeError, ValueError):
        raise ValueError(f"{title}: a row has no valid r attribute") from None


def _cell_column(title: str, cell_el) -> int:
    m = _REF.match(cell_el.get("r") or "")
    if not m:
        raise ValueError(f"{title}: a cell has no valid r attribute")
    return _col_index(m.group(1))


def _set_cell(sheet_root, title: str, ref: str, value) -> None:
    col, row = _parse_ref(title, ref)
    _check_value(f"{title}!{ref}", value)
    data = sheet_root.find(f"{{{NS}}}sheetData")
    if data is None:
        raise ValueError(f"{title} is not a worksheet")
    row_el = None
    for r in data.findall(f"{{{NS}}}row"):
        number = _row_number(title, r)
        if number == row:
            row_el = r
            break
        if number > row:
            row_el = ET.Element(f"{{{NS}}}row", r=str(row))
            data.insert(list(data).index(r), row_el)
            break
    if row_el is None:
        row_el = ET.SubElement(data, f"{{{NS}}}row", r=str(row))
    cell = None
    for c in list(row_el):
        if c.get("r") == ref:
            cell = c
            break
        if _cell_column(title, c) > _col_index(col):
            cell = ET.Element(f"{{{NS}}}c", r=ref)
            row_el.insert(list(row_el).index(c), cell)
            break
    if cell is None:
        cell = ET.SubElement(row_el, f"{{{NS}}}c", r=ref)
    if cell.find(f"{{{NS}}}f") is not None:
        raise ValueError(f"{title}!{ref} holds a formula; the writer only writes value cells")
    # Writing a value cell that formulas depend on leaves those dependents
    # with stale cached values, and a new formula has none, until Excel
    # recalculates: callers that do either pass ``full_calc_on_load=True``.
    # <dimension>, row ``spans`` and the shared-strings count are left stale
    # on purpose; Excel and openpyxl tolerate them.
    for child in list(cell):            # drop <v>, <is>; keep the style attribute
        cell.remove(child)
    cell.attrib.pop("t", None)
    if value is None:
        return
    if isinstance(value, Formula):
        ET.SubElement(cell, f"{{{NS}}}f").text = value.body
    elif isinstance(value, bool):
        cell.set("t", "b")
        ET.SubElement(cell, f"{{{NS}}}v").text = "1" if value else "0"
    elif isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
        ET.SubElement(cell, f"{{{NS}}}v").text = text
    else:
        cell.set("t", "inlineStr")
        is_el = ET.SubElement(cell, f"{{{NS}}}is")
        t = ET.SubElement(is_el, f"{{{NS}}}t")
        if value != value.strip() or "\n" in value:
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = value


def _rewrite(path: Path, replacements: dict) -> None:
    """Write a new zip with ``replacements`` (entry name -> bytes) swapped in
    and every other entry copied as is; replace ``path`` atomically."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w") as dst:
            for info in src.infolist():
                if info.filename in replacements and replacements[info.filename] is None:
                    continue                      # a part the row ops removed
                data = replacements.get(info.filename, src.read(info.filename))
                out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                out.compress_type = info.compress_type
                out.external_attr = info.external_attr
                dst.writestr(out, data)
            names = set(src.namelist())
            for name in sorted(n for n, data in replacements.items()
                               if n not in names and data is not None):
                # A part the edit added (a custom-properties part): a fixed
                # time, so two writes of one book stay byte-identical.
                out = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                out.compress_type = zipfile.ZIP_DEFLATED
                dst.writestr(out, replacements[name])
            dst.comment = src.comment
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _sheet_replacements(z: zipfile.ZipFile, cells: dict, overlay=None) -> tuple:
    parts = _sheet_parts(z)
    replacements, count = {}, 0
    for title, refs in cells.items():
        if title not in parts:
            raise KeyError(f"no sheet named {title!r}")
        source = (overlay or {}).get(parts[title]) or z.read(parts[title])
        root = ET.fromstring(source)
        for ref, value in refs.items():
            _set_cell(root, title, ref, value)
            count += 1
        part = parts[title]
        replacements[part] = _checked(part, _serialize_like(part, source, root))
    return replacements, count


#: A custom-properties part with no property yet (what Excel writes, emptied).
_EMPTY_CUSTOM = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 b'<Properties xmlns="' + NS_CP.encode() + b'" xmlns:vt="'
                 + NS_VT.encode() + b'"></Properties>')
CONTENT_TYPES = "[Content_Types].xml"
ROOT_RELS = "_rels/.rels"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
CUSTOM_TYPE = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
CUSTOM_REL = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
              "custom-properties")


def _new_custom_part(z: zipfile.ZipFile, overlay: dict) -> bytes:
    """Register an empty ``docProps/custom.xml`` in ``overlay``: its content
    type and its package relationship (a book saved by Excel with no custom
    property has neither). Returns the empty part, for the caller to fill."""
    types_src = overlay.get(CONTENT_TYPES) or z.read(CONTENT_TYPES)
    types = ET.fromstring(types_src)
    if not any(o.get("PartName") == "/" + CUSTOM for o in types.iter(f"{{{NS_CT}}}Override")):
        ET.SubElement(types, f"{{{NS_CT}}}Override", PartName="/" + CUSTOM,
                      ContentType=CUSTOM_TYPE)
    overlay[CONTENT_TYPES] = _checked(CONTENT_TYPES,
                                      _serialize_like(CONTENT_TYPES, types_src, types))
    rels_src = overlay.get(ROOT_RELS) or z.read(ROOT_RELS)
    rels = ET.fromstring(rels_src)
    found = list(rels.iter(f"{{{NS_REL}}}Relationship"))
    if not any(r.get("Type") == CUSTOM_REL for r in found):
        taken = {r.get("Id") for r in found}
        n = 1
        while f"rId{n}" in taken:
            n += 1
        ET.SubElement(rels, f"{{{NS_REL}}}Relationship", Id=f"rId{n}", Type=CUSTOM_REL,
                      Target=CUSTOM)
    overlay[ROOT_RELS] = _checked(ROOT_RELS, _serialize_like(ROOT_RELS, rels_src, rels))
    return _EMPTY_CUSTOM


def _custom_replacement(z: zipfile.ZipFile, props: dict, overlay: dict) -> bytes:
    if CUSTOM in overlay:
        source = overlay[CUSTOM]
    elif CUSTOM in z.namelist():
        source = z.read(CUSTOM)
    else:
        source = _new_custom_part(z, overlay)
    root = ET.fromstring(source)
    for key, value in props.items():
        if not isinstance(key, str):
            raise ValueError(f"custom property name {key!r} is not a string")
        _check_value(f"custom property {key!r}", key)
        if value is None:
            raise ValueError(f"custom property {key!r} cannot be None")
        _check_value(f"custom property {key!r}", str(value))
    existing = {p.get("name"): p for p in root.iter(f"{{{NS_CP}}}property")}
    pid = max([int(p.get("pid")) for p in existing.values()] + [1])
    for key, value in props.items():
        p = existing.get(key)
        if p is None:
            pid += 1
            p = ET.SubElement(root, f"{{{NS_CP}}}property", fmtid=FMTID, pid=str(pid), name=key)
        for child in list(p):
            p.remove(child)
        ET.SubElement(p, f"{{{NS_VT}}}lpwstr").text = str(value)
    return _checked(CUSTOM, _serialize_like(CUSTOM, source, root))


#: ``CT_Workbook``'s children that come after ``calcPr`` (ECMA-376 part 1,
#: 18.2.27): a new ``calcPr`` goes before the first of them.
_AFTER_CALC = ("oleSize", "customWorkbookViews", "pivotCaches", "smartTagPr",
               "smartTagTypes", "webPublishing", "fileRecoveryPr", "webPublishObjects",
               "extLst")


def _calc_replacement(z: zipfile.ZipFile, overlay=None):
    """``xl/workbook.xml`` with ``fullCalcOnLoad="1"`` on its ``calcPr``, or
    None when it already says so."""
    source = (overlay or {}).get(WORKBOOK) or z.read(WORKBOOK)
    root = ET.fromstring(source)
    calc = root.find(f"{{{NS}}}calcPr")
    if calc is not None and calc.get("fullCalcOnLoad") in ("1", "true"):
        return None
    if calc is None:
        calc = ET.Element(f"{{{NS}}}calcPr")
        after = {f"{{{NS}}}{name}" for name in _AFTER_CALC}
        at = next((i for i, child in enumerate(root) if child.tag in after), len(root))
        root.insert(at, calc)
    calc.set("fullCalcOnLoad", "1")
    return _checked(WORKBOOK, _serialize_like(WORKBOOK, source, root))


#: ``CT_Workbook``'s children that come after ``definedNames`` (ECMA-376
#: part 1, 18.2.27): a new ``definedNames`` goes before the first of them.
_AFTER_NAMES = ("calcPr",) + _AFTER_CALC
_NAME = re.compile(r"^[A-Za-z_\\][A-Za-z0-9_.\\]*$")
#: Names Excel reads as R1C1 references (``R``, ``C``, ``RC``, ``R2C3``,
#: ``R2``, ``C3``; any case), so refuses as defined names.
_R1C1 = re.compile(r"^(R[0-9]*C[0-9]*|R[0-9]*|C[0-9]*)$", re.IGNORECASE)
#: Excel's longest defined name.
_NAME_MAX = 255


def _accepted_name(name) -> bool:
    """Would Excel take ``name`` as a defined name: its characters, at most
    255 of them, and not a cell reference in either notation (``AB12``,
    ``R2C3``, ``R``, ``C``)."""
    return (isinstance(name, str) and len(name) <= _NAME_MAX and _NAME.match(name) is not None
            and not _REF.match(name.upper()) and not _R1C1.match(name))


def _names_replacement(z: zipfile.ZipFile, names: dict, overlay=None) -> bytes:
    """``xl/workbook.xml`` with each of ``names`` (``{name: text}``) a
    workbook-scoped defined name holding ``text``: an existing one's text
    replaced, a new one appended. Names match as Excel matches them, case
    blind: ``demo.total`` replaces ``DEMO.TOTAL`` (which keeps its
    spelling), and two spellings in one edit are one name -- a second
    workbook-scoped name of either spelling would be a duplicate Excel
    repairs on open."""
    source = (overlay or {}).get(WORKBOOK) or z.read(WORKBOOK)
    root = ET.fromstring(source)
    for name, text in names.items():
        if not _accepted_name(name):
            raise ValueError(f"{name!r} is not a defined name Excel accepts")
        if not isinstance(text, str) or not text or _BAD_CHAR.search(text):
            raise ValueError(f"the defined name {name}: {text!r} is not a reference")
    holder = root.find(f"{{{NS}}}definedNames")
    if holder is None:
        holder = ET.Element(f"{{{NS}}}definedNames")
        after = {f"{{{NS}}}{tag}" for tag in _AFTER_NAMES}
        at = next((i for i, child in enumerate(root) if child.tag in after), len(root))
        root.insert(at, holder)
    existing = {(dn.get("name") or "").upper(): dn
                for dn in holder.findall(f"{{{NS}}}definedName")
                if dn.get("localSheetId") is None}
    for name, text in names.items():
        dn = existing.get(name.upper())
        if dn is None:
            dn = ET.SubElement(holder, f"{{{NS}}}definedName", name=name)
            existing[name.upper()] = dn           # a second spelling in this edit finds it
        dn.text = text
    return _checked(WORKBOOK, _serialize_like(WORKBOOK, source, root))


@dataclass(frozen=True)
class Edited:
    """What ``edit`` wrote: the cells written, and each cell formula on a
    ``lost_ok`` sheet that a row delete left reading ``#REF!``
    (``(sheet, cell, formula)``)."""
    cells_written: int
    lost: list = field(default_factory=list)


def edit(path, *, rows=(), cells: dict | None = None, properties: dict | None = None,
         names: dict | None = None, full_calc_on_load: bool = False, lost_ok=()) -> Edited:
    """Patch an .xlsx in one atomic rewrite: whole-row ``rows`` ops first
    (``exchange.rowops``: ``InsertRows``, ``FillRows``, ``DeleteRows``,
    applied in order), then ``cells`` (``{sheet title: {ref: value}}``,
    addressed as the sheets stand after the row ops; ``None`` clears),
    ``properties`` (string custom document properties; the part is created
    when the book has none) and ``names`` (workbook-scoped defined names,
    ``{name: "'Sheet'!$A$1"}``, added or replaced). Row ops always ask Excel for a full
    calculation on open (they drop the calculation chain); otherwise
    ``full_calc_on_load`` decides. ``lost_ok``: sheet titles whose cell
    formulas may lose a reference to a deleted row (they read ``#REF!``,
    as Excel's own delete leaves them; ``Edited.lost`` lists them); anywhere
    else that is a ``rowops.RowOpError``. Nothing is written on any error."""
    path = Path(path)
    rows = list(rows)
    lost = []
    with zipfile.ZipFile(path) as z:
        overlay = {}
        if rows:
            from estimating_tools.exchange import rowops

            outcome = rowops.apply(z, rows, lost_ok=frozenset(lost_ok))
            overlay.update(outcome.replacements)
            lost = list(outcome.lost)
            full_calc_on_load = True
        replacements, count = _sheet_replacements(z, cells or {}, overlay)
        overlay.update(replacements)
        if properties:
            overlay[CUSTOM] = _custom_replacement(z, properties, overlay)
        if names:
            overlay[WORKBOOK] = _names_replacement(z, names, overlay)
        if full_calc_on_load:
            calc = _calc_replacement(z, overlay)
            if calc is not None:
                overlay[WORKBOOK] = calc
    if overlay:
        _rewrite(path, overlay)
    return Edited(cells_written=count, lost=lost)


def write(path, cells: dict | None = None, properties: dict | None = None, *,
          full_calc_on_load: bool = False) -> int:
    """Cells and properties only (no row ops); see :func:`edit`. Returns the
    number of cells written."""
    return edit(path, cells=cells, properties=properties,
                full_calc_on_load=full_calc_on_load).cells_written


def write_cells(path, cells: dict) -> int:
    """Write ``{sheet title: {ref: value}}``; see :func:`edit`."""
    return write(path, cells=cells)


def set_custom_properties(path, props: dict) -> None:
    """Set or add string custom document properties; see :func:`edit`."""
    write(path, properties=props)


_NO_VALUE = object()


def _set_cached(cell, where: str, value) -> None:
    """Replace a formula cell's cached value (``<v>`` and ``t``); ``_NO_VALUE``
    removes it. The ``<f>`` and every attribute but ``t`` stay as they are."""
    for v in cell.findall(f"{{{NS}}}v"):
        cell.remove(v)
    cell.attrib.pop("t", None)
    if value is _NO_VALUE:
        return
    if isinstance(value, CachedError):
        t, text = "e", value.code
    else:
        _check_value(where, value)
        if value is None:
            raise ValueError(f"{where}: a cached value cannot be None")
        if isinstance(value, bool):
            t, text = "b", "1" if value else "0"
        elif isinstance(value, (int, float)):
            t, text = None, repr(value) if isinstance(value, float) else str(value)
        else:
            t, text = "str", value
    if t:
        cell.set("t", t)
    f = cell.find(f"{{{NS}}}f")
    v = ET.Element(f"{{{NS}}}v")
    v.text = text
    cell.insert(list(cell).index(f) + 1, v)


def write_cached(path, values: dict) -> int:
    """Set the cached value of formula cells in one atomic rewrite.

    ``values`` is ``{sheet title: {ref: value}}``, a value being ``str``,
    ``int``, finite ``float``, ``bool`` or :class:`CachedError`. Every
    formula cell of every worksheet that ``values`` does not name loses its
    cached value, so none is left from before. Only ``<v>`` and the ``t``
    attribute of formula cells change; formulas, styles, value cells and
    every other part are kept (parts byte for byte). ``xl/calcChain.xml`` is
    not touched. Returns the number of values written. ``KeyError`` for an
    unknown sheet; ``ValueError`` for a ref that is not a formula cell or a
    value that cannot be written. Nothing is written on any error."""
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        parts = _sheet_parts(z)
        for title in values:
            if title not in parts:
                raise KeyError(f"no sheet named {title!r}")
        replacements, count = {}, 0
        for title, part in parts.items():
            if "worksheets/" not in part:
                continue                    # a chartsheet holds no cells
            source = z.read(part)
            root = ET.fromstring(source)
            mine = dict(values.get(title) or {})
            changed = False
            for cell in root.iter(f"{{{NS}}}c"):
                if cell.find(f"{{{NS}}}f") is None:
                    continue
                ref = cell.get("r")
                value = mine.pop(ref, _NO_VALUE)
                _set_cached(cell, f"{title}!{ref}", value)
                changed = True
                count += value is not _NO_VALUE
            if mine:
                ref = next(iter(mine))
                raise ValueError(f"{title}!{ref} holds no formula; only formula cells "
                                 "take a cached value")
            if changed:
                replacements[part] = _checked(part, _serialize_like(part, source, root))
    if replacements:
        _rewrite(path, replacements)
    return count
